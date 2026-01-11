#!/usr/bin/env python3
"""
AWS Infrastructure Uninstaller
This script deletes all AWS infrastructure resources created by installer.py.
"""

import boto3
import time
import logging
from botocore.exceptions import ClientError

# Configuration
project_name = "mcp" # at least 3 characters
region = "us-west-2"

sts_client = boto3.client("sts", region_name=region)
account_id = sts_client.get_caller_identity()["Account"]

# Initialize boto3 clients
s3_client = boto3.client("s3", region_name=region)
iam_client = boto3.client("iam", region_name=region)
secrets_client = boto3.client("secretsmanager", region_name=region)
opensearch_client = boto3.client("opensearchserverless", region_name=region)
ec2_client = boto3.client("ec2", region_name=region)
elbv2_client = boto3.client("elbv2", region_name=region)
cloudfront_client = boto3.client("cloudfront", region_name=region)
bedrock_agent_client = boto3.client("bedrock-agent", region_name=region)
bedrock_agentcore_client = boto3.client("bedrock-agentcore-control", region_name=region)

# Get account ID if not set
if not account_id:
    account_id = sts_client.get_caller_identity()["Account"]

bucket_name = f"storage-for-{project_name}-{account_id}-{region}"

# Configure logging
def setup_logging():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    return logging.getLogger(__name__)

logger = setup_logging()

def delete_cloudfront_distributions():
    """Delete CloudFront distributions."""
    logger.info("[1/9] Deleting CloudFront distributions")
    
    try:
        distributions = cloudfront_client.list_distributions()
        for dist in distributions.get("DistributionList", {}).get("Items", []):
            if project_name in dist.get("Comment", ""):
                dist_id = dist["Id"]
                logger.info(f"  Disabling distribution: {dist_id}")
                
                # Get current config
                config_response = cloudfront_client.get_distribution_config(Id=dist_id)
                config = config_response["DistributionConfig"]
                etag = config_response["ETag"]
                
                # Disable distribution
                config["Enabled"] = False
                cloudfront_client.update_distribution(
                    Id=dist_id,
                    DistributionConfig=config,
                    IfMatch=etag
                )
                
                logger.info(f"  Distribution {dist_id} disabled, will be deleted after deployment")
        
        logger.info("✓ CloudFront distributions processed")
    except Exception as e:
        logger.error(f"Error processing CloudFront distributions: {e}")

def delete_disabled_cloudfront_distributions():
    """Delete disabled CloudFront distributions."""
    logger.info("Deleting disabled CloudFront distributions")
    
    try:
        distributions = cloudfront_client.list_distributions()
        for dist in distributions.get("DistributionList", {}).get("Items", []):
            if project_name in dist.get("Comment", "") and not dist.get("Enabled", True):
                dist_id = dist["Id"]
                logger.info(f"  Deleting disabled distribution: {dist_id}")
                
                try:
                    # Get current config and ETag
                    config_response = cloudfront_client.get_distribution_config(Id=dist_id)
                    etag = config_response["ETag"]
                    
                    # Delete distribution
                    cloudfront_client.delete_distribution(
                        Id=dist_id,
                        IfMatch=etag
                    )
                    logger.info(f"  ✓ Deleted distribution: {dist_id}")
                except ClientError as e:
                    if e.response["Error"]["Code"] == "DistributionNotDisabled":
                        logger.info(f"  Distribution {dist_id} is not fully disabled yet, skipping")
                    elif e.response["Error"]["Code"] == "NoSuchDistribution":
                        logger.debug(f"  Distribution {dist_id} already deleted")
                    else:
                        logger.warning(f"  Could not delete distribution {dist_id}: {e}")
        
        logger.info("✓ Disabled CloudFront distributions processed")
    except Exception as e:
        logger.error(f"Error deleting disabled CloudFront distributions: {e}")

def delete_alb_resources():
    """Delete ALB, target groups, and listeners."""
    logger.info("[2/9] Deleting ALB resources")
    
    try:
        # Delete ALB and its listeners first
        alb_name = f"alb-for-{project_name}"
        try:
            albs = elbv2_client.describe_load_balancers(Names=[alb_name])
            if albs["LoadBalancers"]:
                alb_arn = albs["LoadBalancers"][0]["LoadBalancerArn"]
                
                # Delete listeners first
                listeners = elbv2_client.describe_listeners(LoadBalancerArn=alb_arn)
                for listener in listeners["Listeners"]:
                    elbv2_client.delete_listener(ListenerArn=listener["ListenerArn"])
                    logger.info(f"  ✓ Deleted listener: {listener['ListenerArn']}")
                
                # Delete ALB
                elbv2_client.delete_load_balancer(LoadBalancerArn=alb_arn)
                logger.info(f"  ✓ Deleted ALB: {alb_name}")
                
                # Wait for ALB to be deleted
                time.sleep(30)
        except ClientError as e:
            if e.response["Error"]["Code"] != "LoadBalancerNotFound":
                raise
        
        # Delete target groups after ALB is deleted
        tgs = elbv2_client.describe_target_groups()
        for tg in tgs["TargetGroups"]:
            if f"TG-for-{project_name}" in tg["TargetGroupName"]:
                try:
                    elbv2_client.delete_target_group(TargetGroupArn=tg["TargetGroupArn"])
                    logger.info(f"  ✓ Deleted target group: {tg['TargetGroupName']}")
                except ClientError as e:
                    if e.response["Error"]["Code"] != "ResourceInUse":
                        logger.warning(f"  Could not delete target group {tg['TargetGroupName']}: {e}")
        
        logger.info("✓ ALB resources deleted")
    except Exception as e:
        logger.error(f"Error deleting ALB resources: {e}")

def delete_nat_gateways():
    """Delete NAT gateways and their associated routes."""
    logger.info("[3.5/9] Deleting NAT gateways")
    
    try:
        # Get all NAT gateways that match the project name
        nat_gws = ec2_client.describe_nat_gateways()
        project_nat_gws = []
        
        for nat_gw in nat_gws["NatGateways"]:
            if nat_gw["State"] not in ["deleted", "deleting"]:
                # Check if NAT gateway has project name in tags
                nat_gw_id = nat_gw["NatGatewayId"]
                try:
                    tags_response = ec2_client.describe_tags(
                        Filters=[
                            {"Name": "resource-id", "Values": [nat_gw_id]},
                            {"Name": "resource-type", "Values": ["nat-gateway"]}
                        ]
                    )
                    for tag in tags_response.get("Tags", []):
                        if tag.get("Key") == "Name" and project_name in tag.get("Value", ""):
                            project_nat_gws.append(nat_gw)
                            logger.info(f"  Found NAT gateway to delete: {nat_gw_id} ({tag.get('Value')})")
                            break
                except Exception as e:
                    logger.debug(f"  Error checking tags for NAT gateway {nat_gw_id}: {e}")
        
        if not project_nat_gws:
            logger.info("  No NAT gateways found to delete")
            return
        
        # Delete each NAT gateway
        deleted_nat_gw_ids = []
        for nat_gw in project_nat_gws:
            nat_gw_id = nat_gw["NatGatewayId"]
            vpc_id = nat_gw["VpcId"]
            
            logger.info(f"  Deleting NAT gateway: {nat_gw_id}")
            
            # First, remove all routes that reference this NAT gateway
            try:
                route_tables = ec2_client.describe_route_tables(
                    Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
                )
                for rt in route_tables["RouteTables"]:
                    routes_to_remove = []
                    for route in rt["Routes"]:
                        if route.get("NatGatewayId") == nat_gw_id:
                            routes_to_remove.append(route)
                    
                    # Remove routes that reference this NAT gateway
                    for route in routes_to_remove:
                        try:
                            ec2_client.delete_route(
                                RouteTableId=rt["RouteTableId"],
                                DestinationCidrBlock=route["DestinationCidrBlock"]
                            )
                            logger.info(f"    ✓ Removed route {route['DestinationCidrBlock']} -> {nat_gw_id} from route table {rt['RouteTableId']}")
                        except ClientError as route_error:
                            if route_error.response["Error"]["Code"] != "InvalidRoute.NotFound":
                                logger.warning(f"    Could not remove route from {rt['RouteTableId']}: {route_error}")
            except Exception as route_cleanup_error:
                logger.warning(f"    Error cleaning up routes for NAT gateway {nat_gw_id}: {route_cleanup_error}")
            
            # Wait a moment for route deletion to propagate
            time.sleep(5)
            
            # Now delete the NAT gateway
            try:
                ec2_client.delete_nat_gateway(NatGatewayId=nat_gw_id)
                logger.info(f"    ✓ Deleted NAT Gateway: {nat_gw_id}")
                deleted_nat_gw_ids.append(nat_gw_id)
            except ClientError as nat_error:
                logger.warning(f"    Could not delete NAT gateway {nat_gw_id}: {nat_error}")
        
        # Wait for NAT gateways to be deleted only if there are any being deleted
        if deleted_nat_gw_ids:
            # Check if any NAT gateways are still in deleting state
            try:
                nat_gws_status = ec2_client.describe_nat_gateways(NatGatewayIds=deleted_nat_gw_ids)
                deleting_nat_gws = [
                    ngw for ngw in nat_gws_status.get("NatGateways", [])
                    if ngw["State"] == "deleting"
                ]
                
                if deleting_nat_gws:
                    logger.info(f"  Waiting for {len(deleting_nat_gws)} NAT gateway(s) to be deleted...")
                    time.sleep(60)
            except ClientError as e:
                # If NAT gateways are already deleted, describe_nat_gateways will fail
                if e.response["Error"]["Code"] == "InvalidNatGatewayID.NotFound":
                    logger.debug("  NAT gateways already deleted")
                else:
                    logger.debug(f"  Could not check NAT gateway status: {e}")
        
        logger.info("✓ NAT gateways deleted")
    except Exception as e:
        logger.error(f"Error deleting NAT gateways: {e}")

def delete_ec2_instances():
    """Delete EC2 instances."""
    logger.info("[3/9] Deleting EC2 instances")
    
    try:
        instances = ec2_client.describe_instances(
            Filters=[
                {"Name": "tag:Name", "Values": [f"app-for-{project_name}"]},
                {"Name": "instance-state-name", "Values": ["running", "pending", "stopping", "stopped"]}
            ]
        )
        
        instance_ids = []
        for reservation in instances["Reservations"]:
            for instance in reservation["Instances"]:
                instance_ids.append(instance["InstanceId"])
        
        if instance_ids:
            ec2_client.terminate_instances(InstanceIds=instance_ids)
            logger.info(f"  ✓ Terminated instances: {instance_ids}")
            
            # Wait for termination
            waiter = ec2_client.get_waiter('instance_terminated')
            waiter.wait(InstanceIds=instance_ids)
            logger.info("  ✓ Instances terminated")
        
        logger.info("✓ EC2 instances deleted")
    except Exception as e:
        logger.error(f"Error deleting EC2 instances: {e}")

def delete_single_vpc(vpc_id: str) -> bool:
    """Delete a single VPC and all its related resources.
    
    Returns:
        bool: True if VPC was successfully deleted, False otherwise.
    """
    logger.info(f"  Deleting VPC: {vpc_id}")
    
    try:
        # Delete VPC endpoints first with comprehensive waiting
        try:
            endpoints = ec2_client.describe_vpc_endpoints(
                Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
            )
            
            endpoints_to_wait = []
            for endpoint in endpoints["VpcEndpoints"]:
                if endpoint["State"] not in ["deleted"]:
                    endpoints_to_wait.append(endpoint)
                    endpoint_id = endpoint["VpcEndpointId"]
                    
                    if endpoint["State"] not in ["deleting"]:
                        try:
                            ec2_client.delete_vpc_endpoints(VpcEndpointIds=[endpoint_id])
                            logger.info(f"    ✓ Initiated deletion of VPC endpoint: {endpoint_id}")
                        except ClientError as endpoint_error:
                            if endpoint_error.response["Error"]["Code"] != "InvalidVpcEndpointId.NotFound":
                                logger.warning(f"    Could not delete VPC endpoint {endpoint_id}: {endpoint_error}")
                    else:
                        logger.info(f"    VPC endpoint {endpoint_id} already deleting")
            
            # Wait for VPC endpoints to be fully deleted
            if endpoints_to_wait:
                logger.info(f"    Waiting for {len(endpoints_to_wait)} VPC endpoint(s) to be deleted...")
                max_endpoint_wait = 300  # 5 minutes
                endpoint_waited = 0
                
                while endpoint_waited < max_endpoint_wait:
                    remaining_endpoints = []
                    
                    for endpoint in endpoints_to_wait:
                        try:
                            current_endpoints = ec2_client.describe_vpc_endpoints(
                                VpcEndpointIds=[endpoint["VpcEndpointId"]]
                            )
                            if current_endpoints.get("VpcEndpoints"):
                                current_endpoint = current_endpoints["VpcEndpoints"][0]
                                if current_endpoint["State"] not in ["deleted"]:
                                    remaining_endpoints.append(current_endpoint)
                        except ClientError as e:
                            if e.response["Error"]["Code"] == "InvalidVpcEndpointId.NotFound":
                                logger.debug(f"      VPC endpoint {endpoint['VpcEndpointId']} confirmed deleted")
                            else:
                                logger.debug(f"      Error checking VPC endpoint: {e}")
                    
                    if not remaining_endpoints:
                        logger.info(f"    ✓ All VPC endpoints deleted")
                        break
                    
                    logger.info(f"      Still waiting for {len(remaining_endpoints)} VPC endpoint(s)... ({endpoint_waited}s/{max_endpoint_wait}s)")
                    time.sleep(30)
                    endpoint_waited += 30
                
                if remaining_endpoints:
                    logger.warning(f"    ⚠ {len(remaining_endpoints)} VPC endpoint(s) still not deleted after {max_endpoint_wait} seconds")
                    # Continue anyway, but this might cause issues
        except Exception as e:
            logger.info(f"    Error handling VPC endpoints: {e}")
        
        # Delete network interfaces
        try:
            enis = ec2_client.describe_network_interfaces(
                Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
            )
            for eni in enis["NetworkInterfaces"]:
                if eni["Status"] == "available":
                    ec2_client.delete_network_interface(NetworkInterfaceId=eni["NetworkInterfaceId"])
                    logger.info(f"    ✓ Deleted network interface: {eni['NetworkInterfaceId']}")
        except Exception as e:
            logger.warning(f"    Could not delete network interfaces: {e}")
        
        # Delete NAT gateways with proper route cleanup
        nat_gws = ec2_client.describe_nat_gateways(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )
        for nat_gw in nat_gws["NatGateways"]:
            if nat_gw["State"] not in ["deleted", "deleting"]:
                nat_gw_id = nat_gw["NatGatewayId"]
                
                # First, remove all routes that reference this NAT gateway
                try:
                    route_tables = ec2_client.describe_route_tables(
                        Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
                    )
                    for rt in route_tables["RouteTables"]:
                        routes_to_remove = []
                        for route in rt["Routes"]:
                            if route.get("NatGatewayId") == nat_gw_id:
                                routes_to_remove.append(route)
                        
                        # Remove routes that reference this NAT gateway
                        for route in routes_to_remove:
                            try:
                                ec2_client.delete_route(
                                    RouteTableId=rt["RouteTableId"],
                                    DestinationCidrBlock=route["DestinationCidrBlock"]
                                )
                                logger.info(f"    ✓ Removed route {route['DestinationCidrBlock']} -> {nat_gw_id} from route table {rt['RouteTableId']}")
                            except ClientError as route_error:
                                if route_error.response["Error"]["Code"] != "InvalidRoute.NotFound":
                                    logger.warning(f"    Could not remove route from {rt['RouteTableId']}: {route_error}")
                except Exception as route_cleanup_error:
                    logger.warning(f"    Error cleaning up routes for NAT gateway {nat_gw_id}: {route_cleanup_error}")
                
                # Wait a moment for route deletion to propagate
                time.sleep(5)
                
                # Now delete the NAT gateway
                try:
                    ec2_client.delete_nat_gateway(NatGatewayId=nat_gw_id)
                    logger.info(f"    ✓ Deleted NAT Gateway: {nat_gw_id}")
                except ClientError as nat_error:
                    logger.warning(f"    Could not delete NAT gateway {nat_gw_id}: {nat_error}")
        
        # Wait longer for NAT gateways to be deleted
        if nat_gws["NatGateways"]:
            logger.info("    Waiting for NAT gateways to be deleted...")
            time.sleep(60)
        
        # Release Elastic IPs
        eips = ec2_client.describe_addresses()
        for eip in eips["Addresses"]:
            if "NetworkInterfaceId" not in eip and "InstanceId" not in eip:
                try:
                    ec2_client.release_address(AllocationId=eip["AllocationId"])
                    logger.info(f"    ✓ Released EIP: {eip['AllocationId']}")
                except:
                    pass
        
        # Delete security groups with enhanced cleanup
        sgs = ec2_client.describe_security_groups(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )
        
        # First, clean up all security group rules
        for sg in sgs["SecurityGroups"]:
            if sg["GroupName"] != "default":
                try:
                    # Remove all inbound rules
                    if sg.get("IpPermissions"):
                        ec2_client.revoke_security_group_ingress(
                            GroupId=sg["GroupId"],
                            IpPermissions=sg["IpPermissions"]
                        )
                    
                    # Remove all outbound rules (except default)
                    if sg.get("IpPermissionsEgress"):
                        egress_rules = [r for r in sg["IpPermissionsEgress"] 
                                       if not (r.get("IpProtocol") == "-1" and 
                                              len(r.get("IpRanges", [])) == 1 and
                                              r["IpRanges"][0].get("CidrIp") == "0.0.0.0/0")]
                        if egress_rules:
                            ec2_client.revoke_security_group_egress(
                                GroupId=sg["GroupId"],
                                IpPermissions=egress_rules
                            )
                except:
                    pass
        
        time.sleep(10)  # Wait for rule cleanup
        
        # Then delete security groups with retry
        for attempt in range(3):
            remaining_sgs = []
            for sg in sgs["SecurityGroups"]:
                if sg["GroupName"] != "default":
                    try:
                        ec2_client.delete_security_group(GroupId=sg["GroupId"])
                        logger.info(f"    ✓ Deleted security group: {sg['GroupId']}")
                    except ClientError as sg_error:
                        if sg_error.response["Error"]["Code"] not in ["InvalidGroup.NotFound"]:
                            remaining_sgs.append(sg)
            
            if not remaining_sgs:
                break
            elif attempt < 2:
                logger.info(f"    Retrying {len(remaining_sgs)} security groups in 15 seconds...")
                time.sleep(15)
                sgs["SecurityGroups"] = remaining_sgs
        
        # Delete subnets with retry
        subnets = ec2_client.describe_subnets(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )
        for subnet in subnets["Subnets"]:
            subnet_id = subnet["SubnetId"]
            for attempt in range(3):
                try:
                    ec2_client.delete_subnet(SubnetId=subnet_id)
                    logger.info(f"    ✓ Deleted subnet: {subnet_id}")
                    break
                except ClientError as e:
                    if e.response["Error"]["Code"] == "DependencyViolation":
                        if attempt < 2:
                            logger.info(f"    Retrying subnet deletion in 30s: {subnet_id}")
                            time.sleep(30)
                        else:
                            logger.warning(f"    Could not delete subnet {subnet_id}: {e}")
                    else:
                        logger.warning(f"    Could not delete subnet {subnet_id}: {e}")
                        break
        
        # Delete route tables
        route_tables = ec2_client.describe_route_tables(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )
        for rt in route_tables["RouteTables"]:
            if not any(assoc.get("Main") for assoc in rt["Associations"]):
                ec2_client.delete_route_table(RouteTableId=rt["RouteTableId"])
                logger.info(f"    ✓ Deleted route table: {rt['RouteTableId']}")
        
        # Delete internet gateway
        igws = ec2_client.describe_internet_gateways(
            Filters=[{"Name": "attachment.vpc-id", "Values": [vpc_id]}]
        )
        for igw in igws["InternetGateways"]:
            ec2_client.detach_internet_gateway(
                InternetGatewayId=igw["InternetGatewayId"],
                VpcId=vpc_id
            )
            ec2_client.delete_internet_gateway(InternetGatewayId=igw["InternetGatewayId"])
            logger.info(f"    ✓ Deleted internet gateway: {igw['InternetGatewayId']}")
        
        # Delete VPC with retry and complete cleanup
        vpc_deleted = False
        for attempt in range(5):  # Increased attempts
            try:
                ec2_client.delete_vpc(VpcId=vpc_id)
                logger.info(f"  ✓ VPC deletion initiated: {vpc_id}")
                
                # Wait and verify VPC deletion
                logger.info(f"    Waiting for VPC {vpc_id} to be deleted...")
                max_wait = 180  # Increased wait time to 3 minutes
                waited = 0
                while waited < max_wait:
                    try:
                        vpcs = ec2_client.describe_vpcs(VpcIds=[vpc_id])
                        if not vpcs.get("Vpcs"):
                            vpc_deleted = True
                            logger.info(f"  ✓ VPC {vpc_id} successfully deleted")
                            break
                        time.sleep(10)  # Increased check interval
                        waited += 10
                    except ClientError as check_error:
                        if check_error.response["Error"]["Code"] == "InvalidVpcID.NotFound":
                            vpc_deleted = True
                            logger.info(f"  ✓ VPC {vpc_id} successfully deleted")
                            break
                        raise
                
                if vpc_deleted:
                    break
                else:
                    logger.warning(f"    VPC {vpc_id} deletion timed out after {max_wait} seconds")
                    
            except ClientError as e:
                if e.response["Error"]["Code"] == "DependencyViolation":
                    if attempt < 3:
                        logger.info(f"    VPC has dependencies, performing thorough cleanup (attempt {attempt + 1}/5)...")
                        
                        # More thorough dependency cleanup
                        try:
                            # Force delete any remaining network interfaces
                            enis = ec2_client.describe_network_interfaces(
                                Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
                            )
                            for eni in enis["NetworkInterfaces"]:
                                if eni["Status"] == "available":
                                    try:
                                        ec2_client.delete_network_interface(NetworkInterfaceId=eni["NetworkInterfaceId"])
                                        logger.info(f"    ✓ Force deleted network interface: {eni['NetworkInterfaceId']}")
                                    except:
                                        pass
                            
                            # Delete any remaining network ACLs
                            nacls = ec2_client.describe_network_acls(
                                Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
                            )
                            for nacl in nacls["NetworkAcls"]:
                                if not nacl["IsDefault"]:
                                    try:
                                        ec2_client.delete_network_acl(NetworkAclId=nacl["NetworkAclId"])
                                        logger.info(f"    ✓ Deleted network ACL: {nacl['NetworkAclId']}")
                                    except:
                                        pass
                            
                            # Check for VPC peering connections
                            try:
                                peering_connections = ec2_client.describe_vpc_peering_connections(
                                    Filters=[
                                        {"Name": "requester-vpc-info.vpc-id", "Values": [vpc_id]},
                                        {"Name": "accepter-vpc-info.vpc-id", "Values": [vpc_id]}
                                    ]
                                )
                                for pc in peering_connections["VpcPeeringConnections"]:
                                    if pc["Status"]["Code"] not in ["deleted", "deleting"]:
                                        try:
                                            ec2_client.delete_vpc_peering_connection(
                                                VpcPeeringConnectionId=pc["VpcPeeringConnectionId"]
                                            )
                                            logger.info(f"    ✓ Deleted VPC peering connection: {pc['VpcPeeringConnectionId']}")
                                        except:
                                            pass
                            except:
                                pass
                            
                            # Disassociate DHCP options
                            try:
                                ec2_client.associate_dhcp_options(
                                    DhcpOptionsId="default",
                                    VpcId=vpc_id
                                )
                                logger.info(f"    ✓ Reset DHCP options to default for VPC: {vpc_id}")
                            except:
                                pass
                                
                        except Exception as cleanup_error:
                            logger.debug(f"    Error during thorough cleanup: {cleanup_error}")
                        
                        # Wait longer between attempts
                        wait_time = 60 + (attempt * 30)  # Progressive wait: 60s, 90s, 120s, 150s
                        logger.info(f"    Waiting {wait_time} seconds before retry...")
                        time.sleep(wait_time)
                    else:
                        logger.error(f"  ✗ Failed to delete VPC {vpc_id} after 5 attempts: {e}")
                        break
                elif e.response["Error"]["Code"] == "InvalidVpcID.NotFound":
                    # VPC already deleted
                    vpc_deleted = True
                    logger.info(f"  ✓ VPC {vpc_id} already deleted")
                    break
                else:
                    logger.error(f"  ✗ Failed to delete VPC {vpc_id}: {e}")
                    break
        
        if not vpc_deleted:
            logger.error(f"  ✗ VPC {vpc_id} was not deleted. Please check dependencies manually.")
            # Final verification attempt
            try:
                vpcs = ec2_client.describe_vpcs(VpcIds=[vpc_id])
                if vpcs.get("Vpcs"):
                    logger.error(f"  ✗ VPC {vpc_id} still exists. Remaining resources will be retried after CloudFront cleanup.")
                    return False
            except ClientError as final_check:
                if final_check.response["Error"]["Code"] == "InvalidVpcID.NotFound":
                    logger.info(f"  ✓ VPC {vpc_id} was actually deleted (final check)")
                    return True
                else:
                    logger.error(f"  ✗ Could not verify VPC deletion status: {final_check}")
                    return False
        
        return vpc_deleted
    except Exception as e:
        logger.error(f"Error deleting VPC {vpc_id}: {e}")
        return False

def delete_vpc_resources():
    """Delete VPC and related resources.
    
    Returns:
        list: List of VPC IDs that failed to delete.
    """
    logger.info("[4/9] Deleting VPC resources")
    
    failed_vpcs = []
    
    try:
        # Find all VPCs that might be related to the project
        vpc_name = f"vpc-for-{project_name}"
        
        # First, try to find VPCs by tag name
        vpcs_by_tag = ec2_client.describe_vpcs(
            Filters=[{"Name": "tag:Name", "Values": [vpc_name]}]
        )
        
        # Also get all VPCs to check for any that might be related
        all_vpcs = ec2_client.describe_vpcs()
        
        # Collect VPCs to delete
        vpcs_to_delete = []
        vpc_ids_found = set()
        
        # Add VPCs found by tag
        for vpc in vpcs_by_tag.get("Vpcs", []):
            vpc_id = vpc["VpcId"]
            if vpc_id not in vpc_ids_found:
                vpcs_to_delete.append(vpc_id)
                vpc_ids_found.add(vpc_id)
        
        # Check all VPCs for project-related resources (subnets, security groups, etc.)
        for vpc in all_vpcs.get("Vpcs", []):
            vpc_id = vpc["VpcId"]
            if vpc_id in vpc_ids_found:
                continue
            
            # First, check if VPC has the correct name tag
            vpc_has_name_tag = False
            for tag in vpc.get("Tags", []):
                if tag.get("Key") == "Name" and tag.get("Value") == vpc_name:
                    vpc_has_name_tag = True
                    vpcs_to_delete.append(vpc_id)
                    vpc_ids_found.add(vpc_id)
                    logger.info(f"  Found VPC by name tag: {vpc_id}")
                    break
            
            # If VPC has the correct name tag, skip checking resources
            if vpc_has_name_tag:
                continue
            
            # Check if VPC has project-related resources
            try:
                # Check subnets
                subnets = ec2_client.describe_subnets(
                    Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
                )
                has_project_subnets = False
                for subnet in subnets.get("Subnets", []):
                    for tag in subnet.get("Tags", []):
                        if project_name in tag.get("Value", ""):
                            has_project_subnets = True
                            break
                    if has_project_subnets:
                        break
                
                # Check security groups
                sgs = ec2_client.describe_security_groups(
                    Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
                )
                has_project_sgs = False
                for sg in sgs.get("SecurityGroups", []):
                    if project_name in sg.get("GroupName", ""):
                        has_project_sgs = True
                        break
                
                # Check NAT gateways
                nat_gws = ec2_client.describe_nat_gateways(
                    Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
                )
                has_project_nat = False
                for nat_gw in nat_gws.get("NatGateways", []):
                    if nat_gw["State"] not in ["deleted", "deleting"]:
                        # Check tags
                        tags_response = ec2_client.describe_tags(
                            Filters=[
                                {"Name": "resource-id", "Values": [nat_gw["NatGatewayId"]]},
                                {"Name": "resource-type", "Values": ["nat-gateway"]}
                            ]
                        )
                        for tag in tags_response.get("Tags", []):
                            if project_name in tag.get("Value", ""):
                                has_project_nat = True
                                break
                        if has_project_nat:
                            break
                
                # If VPC has project-related resources, add it to deletion list
                if has_project_subnets or has_project_sgs or has_project_nat:
                    vpcs_to_delete.append(vpc_id)
                    vpc_ids_found.add(vpc_id)
                    logger.info(f"  Found project-related VPC: {vpc_id}")
            except Exception as e:
                logger.debug(f"  Error checking VPC {vpc_id}: {e}")
        
        if not vpcs_to_delete:
            logger.info("  No VPC found to delete")
            return
        
        logger.info(f"  Found {len(vpcs_to_delete)} VPC(s) to delete: {vpcs_to_delete}")
        
        # Delete each VPC
        for vpc_id in vpcs_to_delete:
            if not delete_single_vpc(vpc_id):
                failed_vpcs.append(vpc_id)
        
        # Final verification: Check if any VPCs still exist
        logger.info("  Verifying VPC deletion...")
        remaining_vpcs = []
        for vpc_id in vpcs_to_delete:
            try:
                vpcs = ec2_client.describe_vpcs(VpcIds=[vpc_id])
                if vpcs.get("Vpcs"):
                    remaining_vpcs.append(vpc_id)
                    logger.warning(f"  ⚠ VPC {vpc_id} still exists")

                    # retry VPC deletion
                    for attempt in range(3):
                        try:
                            ec2_client.delete_vpc(VpcId=vpc_id)
                            logger.info(f"  ✓ VPC deletion initiated: {vpc_id}")
                            break
                        except ClientError as e:
                            if e.response["Error"]["Code"] == "DependencyViolation":
                                if attempt < 2:
                                    logger.info(f"    Retrying VPC deletion in 30s: {vpc_id}")
                                    time.sleep(30)
                                else:
                                    logger.warning(f"    Could not delete VPC {vpc_id}: {e}")
                                    break
                            else:
                                logger.warning(f"    Could not delete VPC {vpc_id}: {e}")
                                break
            except ClientError as e:
                if e.response["Error"]["Code"] == "InvalidVpcID.NotFound":
                    logger.debug(f"  ✓ VPC {vpc_id} confirmed deleted")
                else:
                    logger.warning(f"  Could not verify VPC {vpc_id}: {e}")
        
        if remaining_vpcs:
            logger.error(f"  ✗ {len(remaining_vpcs)} VPC(s) still exist: {remaining_vpcs}")
            logger.error("  Please check AWS console and delete manually if needed")
            # Add remaining VPCs to failed list
            for vpc_id in remaining_vpcs:
                if vpc_id not in failed_vpcs:
                    failed_vpcs.append(vpc_id)
        else:
            logger.info("✓ All VPC resources deleted")
    except Exception as e:
        logger.error(f"Error deleting VPC resources: {e}")
    
    return failed_vpcs

def delete_opensearch_collection():
    """Delete OpenSearch Serverless collection and policies."""
    logger.info("[5/9] Deleting OpenSearch collection")
    
    try:
        collection_name = project_name
        
        # Get collection ID first
        try:
            collections = opensearch_client.list_collections()
            collection_id = None
            for collection in collections.get("collectionSummaries", []):
                if collection["name"] == collection_name:
                    collection_id = collection["id"]
                    break
            
            if collection_id:
                # Delete collection using ID
                opensearch_client.delete_collection(id=collection_id)
                logger.info(f"  ✓ Deleted collection: {collection_name} (ID: {collection_id})")
                
                # Wait for deletion
                time.sleep(30)
            else:
                logger.info(f"  Collection {collection_name} not found")
                
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceNotFoundException":
                logger.warning(f"  Could not delete collection: {e}")
        
        # Delete data access policy (different API)
        try:
            opensearch_client.delete_access_policy(
                name=f"data-{project_name}",
                type="data"
            )
            logger.info(f"  ✓ Deleted data access policy: data-{project_name}")
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceNotFoundException":
                logger.warning(f"  Could not delete data access policy: {e}")
        
        # Delete policies
        policies = [
            ("network", f"net-{project_name}-{region}"),
            ("encryption", f"enc-{project_name}-{region}")
        ]
        
        for policy_type, policy_name in policies:
            try:
                opensearch_client.delete_security_policy(
                    name=policy_name,
                    type=policy_type
                )
                logger.info(f"  ✓ Deleted {policy_type} policy: {policy_name}")
            except ClientError as e:
                if e.response["Error"]["Code"] != "ResourceNotFoundException":
                    logger.warning(f"  Could not delete {policy_type} policy {policy_name}: {e}")
        
        logger.info("✓ OpenSearch collection deleted")
    except Exception as e:
        logger.error(f"Error deleting OpenSearch collection: {e}")

def delete_knowledge_bases():
    """Delete Knowledge Bases and their data sources."""
    logger.info("[5.5/9] Deleting Knowledge Bases")
    
    try:
        # List all knowledge bases
        try:
            kb_list = bedrock_agent_client.list_knowledge_bases()
            knowledge_bases = kb_list.get("knowledgeBaseSummaries", [])
            
            # Find knowledge bases matching project name
            kb_to_delete = []
            for kb in knowledge_bases:
                if kb["name"] == project_name:
                    kb_to_delete.append(kb["knowledgeBaseId"])
                    logger.info(f"  Knowledge Base found: {kb['knowledgeBaseId']}")
                                
            if not kb_to_delete:
                logger.info(f"  No Knowledge Base found with name: {project_name}")
                return
            
            # Delete each knowledge base
            for kb_id in kb_to_delete:
                try:
                    logger.info(f"  Deleting Knowledge Base: {kb_id}")
                    
                    # Delete all data sources first
                    try:
                        data_sources = bedrock_agent_client.list_data_sources(
                            knowledgeBaseId=kb_id,
                            maxResults=100
                        )
                        for ds in data_sources.get("dataSourceSummaries", []):
                            try:
                                bedrock_agent_client.delete_data_source(
                                    knowledgeBaseId=kb_id,
                                    dataSourceId=ds["dataSourceId"]
                                )
                                logger.info(f"    ✓ Deleted data source: {ds['dataSourceId']}")
                            except Exception as e:
                                logger.warning(f"    Could not delete data source {ds['dataSourceId']}: {e}")
                    except Exception as e:
                        logger.debug(f"    Error listing/deleting data sources: {e}")
                    
                    # Delete the knowledge base
                    bedrock_agent_client.delete_knowledge_base(knowledgeBaseId=kb_id)
                    logger.info(f"  ✓ Deleted Knowledge Base: {kb_id}")
                    
                    # Wait for deletion to complete
                    logger.debug("    Waiting for Knowledge Base deletion to complete...")
                    max_wait = 60  # Wait up to 60 seconds
                    waited = 0
                    while waited < max_wait:
                        try:
                            kb_response = bedrock_agent_client.get_knowledge_base(knowledgeBaseId=kb_id)
                            status = kb_response["knowledgeBase"]["status"]
                            if status == "DELETED":
                                break
                            time.sleep(5)
                            waited += 5
                        except ClientError as e:
                            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                                logger.debug("    Knowledge Base deletion confirmed")
                                break
                            raise
                    
                except ClientError as e:
                    if e.response["Error"]["Code"] == "ResourceNotFoundException":
                        logger.debug(f"  Knowledge Base {kb_id} already deleted")
                    else:
                        logger.warning(f"  Could not delete Knowledge Base {kb_id}: {e}")
                except Exception as e:
                    logger.warning(f"  Error deleting Knowledge Base {kb_id}: {e}")
            
            logger.info("✓ Knowledge Bases deleted")
        except Exception as e:
            logger.warning(f"  Could not list Knowledge Bases: {e}")
            
    except Exception as e:
        logger.error(f"Error deleting Knowledge Bases: {e}")

def delete_code_interpreters():
    """Delete Code Interpreters."""
    logger.info("[5.6/9] Deleting Code Interpreters")
    
    try:
        # List all code interpreters
        try:
            # Try to list code interpreters
            # Note: If list API doesn't exist, we'll try to delete by name
            try:
                response = bedrock_agentcore_client.list_code_interpreters()
                code_interpreters = response.get("codeInterpreters", [])
            except ClientError as e:
                # If list API doesn't exist, try to describe by name
                if e.response["Error"]["Code"] == "InvalidRequestException" or "not found" in str(e).lower():
                    logger.debug("  List API not available, trying to delete by name")
                    code_interpreters = []
                else:
                    raise
            
            # Find code interpreters matching project name
            ci_to_delete = []
            for ci in code_interpreters:
                if ci.get("name") == project_name or project_name in ci.get("name", ""):
                    ci_id = ci.get("codeInterpreterId") or ci.get("id")
                    if ci_id:
                        ci_to_delete.append(ci_id)
                        logger.info(f"  Code Interpreter found: {ci_id}")
            
            # If no code interpreters found in list, try to delete by name directly
            if not ci_to_delete:
                logger.info(f"  Trying to delete code interpreter by name: {project_name}")
                try:
                    # Try to describe code interpreter by name
                    response = bedrock_agentcore_client.describe_code_interpreter(
                        codeInterpreterId=project_name
                    )
                    ci_id = response.get("codeInterpreterId") or response.get("id")
                    if ci_id:
                        ci_to_delete.append(ci_id)
                        logger.info(f"  Code Interpreter found: {ci_id}")
                except ClientError as e:
                    if e.response["Error"]["Code"] == "ResourceNotFoundException":
                        logger.info(f"  No Code Interpreter found with name: {project_name}")
                    else:
                        logger.warning(f"  Could not describe code interpreter: {e}")
            
            if not ci_to_delete:
                logger.info(f"  No Code Interpreter found to delete")
                return
            
            # Delete each code interpreter
            for ci_id in ci_to_delete:
                try:
                    logger.info(f"  Deleting Code Interpreter: {ci_id}")
                    bedrock_agentcore_client.delete_code_interpreter(
                        codeInterpreterId=ci_id
                    )
                    logger.info(f"  ✓ Deleted Code Interpreter: {ci_id}")
                    
                    # Wait for deletion to complete
                    logger.debug("    Waiting for Code Interpreter deletion to complete...")
                    max_wait = 60  # Wait up to 60 seconds
                    waited = 0
                    while waited < max_wait:
                        try:
                            response = bedrock_agentcore_client.describe_code_interpreter(
                                codeInterpreterId=ci_id
                            )
                            status = response.get("status", "")
                            if status == "DELETED":
                                break
                            time.sleep(5)
                            waited += 5
                        except ClientError as e:
                            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                                logger.debug("    Code Interpreter deletion confirmed")
                                break
                            raise
                    
                except ClientError as e:
                    if e.response["Error"]["Code"] == "ResourceNotFoundException":
                        logger.debug(f"  Code Interpreter {ci_id} already deleted")
                    else:
                        logger.warning(f"  Could not delete Code Interpreter {ci_id}: {e}")
                except Exception as e:
                    logger.warning(f"  Error deleting Code Interpreter {ci_id}: {e}")
            
            logger.info("✓ Code Interpreters deleted")
        except Exception as e:
            logger.warning(f"  Could not list Code Interpreters: {e}")
            
    except Exception as e:
        logger.error(f"Error deleting Code Interpreters: {e}")


def delete_secrets():
    """Delete Secrets Manager secrets."""
    logger.info("[6/9] Deleting secrets")
    
    secret_names = [
        f"openweathermap-{project_name}",
        f"langsmithapikey-{project_name}",
        f"tavilyapikey-{project_name}",
        f"perplexityapikey-{project_name}",
        f"firecrawlapikey-{project_name}",
        f"code-interpreter-{project_name}",
        f"novaactapikey-{project_name}",
        f"notionapikey-{project_name}"
    ]
    
    for secret_name in secret_names:
        try:
            secrets_client.delete_secret(
                SecretId=secret_name,
                ForceDeleteWithoutRecovery=True
            )
            logger.info(f"  ✓ Deleted secret: {secret_name}")
        except ClientError as e:
            if e.response["Error"]["Code"] != "ResourceNotFoundException":
                logger.warning(f"  Could not delete secret {secret_name}: {e}")
    
    logger.info("✓ Secrets deleted")

def delete_security_groups():
    """Delete security groups with proper dependency handling."""
    logger.info("[4/9] Deleting security groups")
    
    try:
        # Get all security groups
        all_sgs = ec2_client.describe_security_groups()
        
        # Find security groups matching project name pattern
        sgs_to_delete = []
        for sg in all_sgs.get("SecurityGroups", []):
            sg_name = sg.get("GroupName", "")
            # Check if security group name contains project name
            if project_name in sg_name and sg_name != "default":
                sgs_to_delete.append({
                    "GroupId": sg["GroupId"],
                    "GroupName": sg_name,
                    "VpcId": sg.get("VpcId")
                })
        
        if not sgs_to_delete:
            logger.info("  No security groups found to delete")
            return
        
        logger.info(f"  Found {len(sgs_to_delete)} security group(s) to delete")
        
        # Clean up security group rules and dependencies
        cleanup_security_group_dependencies(sgs_to_delete)
        
        # Try to delete security groups with retry logic
        delete_security_groups_with_retry(sgs_to_delete)
        
        logger.info("✓ Security groups processed")
    except Exception as e:
        logger.error(f"Error deleting security groups: {e}")

def cleanup_security_group_dependencies(sgs_to_delete):
    """Clean up security group rules and dependencies."""
    sg_ids_to_delete = {sg["GroupId"] for sg in sgs_to_delete}
    
    # First pass: Remove all rules from security groups to be deleted
    for sg_info in sgs_to_delete:
        try:
            sg_detail = ec2_client.describe_security_groups(GroupIds=[sg_info["GroupId"]])
            if sg_detail.get("SecurityGroups"):
                sg = sg_detail["SecurityGroups"][0]
                
                # Remove all inbound rules
                if sg.get("IpPermissions"):
                    try:
                        ec2_client.revoke_security_group_ingress(
                            GroupId=sg_info["GroupId"],
                            IpPermissions=sg["IpPermissions"]
                        )
                        logger.info(f"  ✓ Removed inbound rules from: {sg_info['GroupName']}")
                    except ClientError as e:
                        if e.response.get("Error", {}).get("Code") != "InvalidPermission.NotFound":
                            logger.debug(f"    Could not remove inbound rules: {e}")
                
                # Remove all outbound rules (except default allow-all)
                if sg.get("IpPermissionsEgress"):
                    egress_rules = []
                    for rule in sg["IpPermissionsEgress"]:
                        # Skip default allow-all egress rule
                        if not (rule.get("IpProtocol") == "-1" and 
                               len(rule.get("IpRanges", [])) == 1 and
                               rule["IpRanges"][0].get("CidrIp") == "0.0.0.0/0"):
                            egress_rules.append(rule)
                    
                    if egress_rules:
                        try:
                            ec2_client.revoke_security_group_egress(
                                GroupId=sg_info["GroupId"],
                                IpPermissions=egress_rules
                            )
                            logger.info(f"  ✓ Removed outbound rules from: {sg_info['GroupName']}")
                        except ClientError as e:
                            if e.response.get("Error", {}).get("Code") != "InvalidPermission.NotFound":
                                logger.debug(f"    Could not remove outbound rules: {e}")
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") != "InvalidGroup.NotFound":
                logger.debug(f"    Could not process security group {sg_info['GroupName']}: {e}")
    
    time.sleep(5)
    
    # Second pass: Remove references from other security groups
    all_sgs_again = ec2_client.describe_security_groups()
    for sg in all_sgs_again.get("SecurityGroups", []):
        if sg["GroupId"] in sg_ids_to_delete:
            continue
        
        # Check and remove inbound rules that reference our security groups
        inbound_to_remove = []
        if sg.get("IpPermissions"):
            for rule in sg["IpPermissions"]:
                for user_id_group_pair in rule.get("UserIdGroupPairs", []):
                    if user_id_group_pair.get("GroupId") in sg_ids_to_delete:
                        inbound_to_remove.append(rule)
                        break
        
        if inbound_to_remove:
            try:
                ec2_client.revoke_security_group_ingress(
                    GroupId=sg["GroupId"],
                    IpPermissions=inbound_to_remove
                )
                logger.info(f"  ✓ Removed references from security group: {sg.get('GroupName', sg['GroupId'])}")
            except ClientError as e:
                logger.debug(f"    Could not remove inbound references: {e}")
        
        # Check and remove outbound rules that reference our security groups
        outbound_to_remove = []
        if sg.get("IpPermissionsEgress"):
            for rule in sg["IpPermissionsEgress"]:
                for user_id_group_pair in rule.get("UserIdGroupPairs", []):
                    if user_id_group_pair.get("GroupId") in sg_ids_to_delete:
                        outbound_to_remove.append(rule)
                        break
        
        if outbound_to_remove:
            try:
                ec2_client.revoke_security_group_egress(
                    GroupId=sg["GroupId"],
                    IpPermissions=outbound_to_remove
                )
                logger.info(f"  ✓ Removed outbound references from security group: {sg.get('GroupName', sg['GroupId'])}")
            except ClientError as e:
                logger.debug(f"    Could not remove outbound references: {e}")
    
    time.sleep(5)

def delete_security_groups_with_retry(sgs_to_delete):
    """Delete security groups with retry logic."""
    deleted_sgs = []
    remaining_sgs = sgs_to_delete.copy()
    
    for attempt in range(5):  # Increased attempts
        if not remaining_sgs:
            break
        
        logger.info(f"  Attempt {attempt + 1}/5: Trying to delete {len(remaining_sgs)} security group(s)")
        
        for sg_info in remaining_sgs[:]:
            try:
                ec2_client.delete_security_group(GroupId=sg_info["GroupId"])
                logger.info(f"  ✓ Deleted security group: {sg_info['GroupName']} ({sg_info['GroupId']})")
                deleted_sgs.append(sg_info)
                remaining_sgs.remove(sg_info)
            except ClientError as e:
                error_code = e.response.get("Error", {}).get("Code", "")
                if error_code == "DependencyViolation":
                    # Check network interfaces
                    try:
                        enis = ec2_client.describe_network_interfaces(
                            Filters=[{"Name": "group-id", "Values": [sg_info["GroupId"]]}]
                        )
                        if enis.get("NetworkInterfaces"):
                            logger.debug(f"    Security group {sg_info['GroupName']} attached to {len(enis['NetworkInterfaces'])} network interface(s)")
                            # Try to detach from available network interfaces
                            for eni in enis["NetworkInterfaces"]:
                                if eni["Status"] == "available":
                                    try:
                                        ec2_client.delete_network_interface(NetworkInterfaceId=eni["NetworkInterfaceId"])
                                        logger.info(f"    ✓ Deleted network interface: {eni['NetworkInterfaceId']}")
                                    except:
                                        pass
                    except:
                        pass
                elif error_code == "InvalidGroup.NotFound":
                    logger.debug(f"  Security group {sg_info['GroupName']} already deleted")
                    deleted_sgs.append(sg_info)
                    remaining_sgs.remove(sg_info)
                else:
                    logger.debug(f"    Could not delete security group {sg_info['GroupName']}: {e}")
        
        if remaining_sgs and attempt < 4:
            wait_time = 15 + (attempt * 10)  # Progressive wait
            logger.info(f"  Waiting {wait_time} seconds before retry...")
            time.sleep(wait_time)
    
    if remaining_sgs:
        logger.warning(f"  ⚠ {len(remaining_sgs)} security group(s) could not be deleted: {[sg['GroupName'] for sg in remaining_sgs]}")
        logger.info("  They will be deleted when VPC is deleted")
    else:
        logger.info(f"  ✓ Successfully deleted {len(deleted_sgs)} security group(s)")

def delete_route_tables():
    """Delete route tables with proper dependency cleanup."""
    logger.info("  Deleting route tables...")
    
    try:
        # Get all route tables for project VPCs
        vpc_name = f"vpc-for-{project_name}"
        vpcs = ec2_client.describe_vpcs(
            Filters=[{"Name": "tag:Name", "Values": [vpc_name]}]
        )
        
        for vpc in vpcs.get("Vpcs", []):
            vpc_id = vpc["VpcId"]
            route_tables = ec2_client.describe_route_tables(
                Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
            )
            
            for rt in route_tables["RouteTables"]:
                if not any(assoc.get("Main") for assoc in rt["Associations"]):
                    rt_id = rt["RouteTableId"]
                    
                    # Disassociate from subnets
                    for assoc in rt["Associations"]:
                        if not assoc.get("Main") and "SubnetId" in assoc:
                            try:
                                ec2_client.disassociate_route_table(
                                    AssociationId=assoc["RouteTableAssociationId"]
                                )
                                logger.info(f"    ✓ Disassociated route table {rt_id} from subnet {assoc['SubnetId']}")
                            except ClientError as e:
                                if e.response["Error"]["Code"] != "InvalidAssociationID.NotFound":
                                    logger.debug(f"    Could not disassociate route table {rt_id}: {e}")
                    
                    time.sleep(2)
                    
                    # Delete the route table
                    try:
                        ec2_client.delete_route_table(RouteTableId=rt_id)
                        logger.info(f"  ✓ Deleted route table: {rt_id} (VPC: {vpc_id})")
                    except ClientError as e:
                        if e.response["Error"]["Code"] != "InvalidRouteTableID.NotFound":
                            logger.debug(f"  Could not delete route table {rt_id}: {e}")
    except Exception as e:
        logger.debug(f"Error deleting route tables: {e}")

def delete_vpc_endpoints_and_wait():
    """Delete VPC endpoints and wait for completion."""
    logger.info("Deleting VPC endpoints...")
    
    try:
        # Find all VPC endpoints for project VPCs
        vpc_name = f"vpc-for-{project_name}"
        vpcs = ec2_client.describe_vpcs(
            Filters=[{"Name": "tag:Name", "Values": [vpc_name]}]
        )
        
        all_endpoints = []
        for vpc in vpcs.get("Vpcs", []):
            vpc_id = vpc["VpcId"]
            endpoints = ec2_client.describe_vpc_endpoints(
                Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
            )
            
            for endpoint in endpoints["VpcEndpoints"]:
                if endpoint["State"] not in ["deleted", "deleting"]:
                    all_endpoints.append(endpoint)
                    logger.info(f"  Found VPC endpoint to delete: {endpoint['VpcEndpointId']} ({endpoint.get('ServiceName', 'Unknown')})")
                elif endpoint["State"] == "deleting":
                    all_endpoints.append(endpoint)
                    logger.info(f"  Found VPC endpoint already deleting: {endpoint['VpcEndpointId']} ({endpoint.get('ServiceName', 'Unknown')})")
        
        # Delete endpoints that are not already deleting
        for endpoint in all_endpoints:
            if endpoint["State"] not in ["deleted", "deleting"]:
                try:
                    ec2_client.delete_vpc_endpoints(VpcEndpointIds=[endpoint["VpcEndpointId"]])
                    logger.info(f"  ✓ Initiated deletion of VPC endpoint: {endpoint['VpcEndpointId']}")
                except ClientError as e:
                    if e.response["Error"]["Code"] != "InvalidVpcEndpointId.NotFound":
                        logger.warning(f"  Could not delete VPC endpoint {endpoint['VpcEndpointId']}: {e}")
        
        # Wait for all endpoints to be deleted
        if all_endpoints:
            logger.info(f"  Waiting for {len(all_endpoints)} VPC endpoint(s) to be deleted...")
            max_wait = 300  # 5 minutes
            waited = 0
            
            while waited < max_wait:
                remaining_endpoints = []
                
                for endpoint in all_endpoints:
                    try:
                        current_endpoints = ec2_client.describe_vpc_endpoints(
                            VpcEndpointIds=[endpoint["VpcEndpointId"]]
                        )
                        if current_endpoints.get("VpcEndpoints"):
                            current_endpoint = current_endpoints["VpcEndpoints"][0]
                            if current_endpoint["State"] not in ["deleted"]:
                                remaining_endpoints.append(current_endpoint)
                                logger.debug(f"    VPC endpoint {endpoint['VpcEndpointId']} still in state: {current_endpoint['State']}")
                    except ClientError as e:
                        if e.response["Error"]["Code"] == "InvalidVpcEndpointId.NotFound":
                            logger.debug(f"    VPC endpoint {endpoint['VpcEndpointId']} confirmed deleted")
                        else:
                            logger.debug(f"    Error checking VPC endpoint {endpoint['VpcEndpointId']}: {e}")
                
                if not remaining_endpoints:
                    logger.info("  ✓ All VPC endpoints deleted")
                    break
                
                logger.info(f"    Still waiting for {len(remaining_endpoints)} VPC endpoint(s)... ({waited}s/{max_wait}s)")
                time.sleep(30)
                waited += 30
            
            if remaining_endpoints:
                logger.warning(f"  ⚠ {len(remaining_endpoints)} VPC endpoint(s) still not deleted after {max_wait} seconds")
                for endpoint in remaining_endpoints:
                    logger.warning(f"    - {endpoint['VpcEndpointId']} (State: {endpoint['State']})")
        
        logger.info("✓ VPC endpoints processed")
    except Exception as e:
        logger.error(f"Error deleting VPC endpoints: {e}")

def wait_for_vpc_endpoint_deletion():
    """Wait for any remaining VPC endpoints to be deleted."""
    logger.info("Checking for remaining VPC endpoints...")
    
    try:
        # Check for the specific VPC endpoint that was deleting
        endpoint_id = "vpce-0463dca454a0900e4"
        
        max_wait = 300  # 5 minutes
        waited = 0
        
        while waited < max_wait:
            try:
                endpoints = ec2_client.describe_vpc_endpoints(VpcEndpointIds=[endpoint_id])
                if endpoints.get("VpcEndpoints"):
                    endpoint = endpoints["VpcEndpoints"][0]
                    if endpoint["State"] == "deleted":
                        logger.info(f"  ✓ VPC endpoint {endpoint_id} is now deleted")
                        break
                    else:
                        logger.info(f"  VPC endpoint {endpoint_id} still in state: {endpoint['State']} (waiting {waited}s/{max_wait}s)")
                        time.sleep(30)
                        waited += 30
                else:
                    logger.info(f"  ✓ VPC endpoint {endpoint_id} is deleted")
                    break
            except ClientError as e:
                if e.response["Error"]["Code"] == "InvalidVpcEndpointId.NotFound":
                    logger.info(f"  ✓ VPC endpoint {endpoint_id} confirmed deleted")
                    break
                else:
                    logger.warning(f"  Error checking VPC endpoint: {e}")
                    break
        
        if waited >= max_wait:
            logger.warning(f"  ⚠ VPC endpoint {endpoint_id} still not deleted after {max_wait} seconds")
            return False
        
        return True
    except Exception as e:
        logger.debug(f"Error waiting for VPC endpoint deletion: {e}")
        return False

def force_delete_specific_security_group():
    """Force delete remaining security groups that are blocking VPC deletion."""
    logger.info("Checking for remaining security groups blocking VPC deletion...")
    
    try:
        # Find all security groups matching project name pattern
        all_sgs = ec2_client.describe_security_groups()
        remaining_sgs = []
        
        for sg in all_sgs.get("SecurityGroups", []):
            sg_name = sg.get("GroupName", "")
            # Check if security group name contains project name and is not default
            if project_name in sg_name and sg_name != "default":
                remaining_sgs.append({
                    "GroupId": sg["GroupId"],
                    "GroupName": sg_name,
                    "VpcId": sg.get("VpcId")
                })
        
        if not remaining_sgs:
            logger.info("  No remaining security groups found to delete")
            return
        
        logger.info(f"  Found {len(remaining_sgs)} remaining security group(s) to force delete: {[sg['GroupName'] for sg in remaining_sgs]}")
        
        # Force delete each remaining security group
        for sg_info in remaining_sgs:
            sg_id = sg_info["GroupId"]
            sg_name = sg_info["GroupName"]
            
            try:
                # Get security group details
                sg_detail = ec2_client.describe_security_groups(GroupIds=[sg_id])
                if not sg_detail.get("SecurityGroups"):
                    logger.debug(f"  Security group {sg_name} ({sg_id}) not found (already deleted)")
                    continue
                
                sg = sg_detail["SecurityGroups"][0]
                logger.info(f"  Force deleting security group: {sg_name} ({sg_id})")
                
                # Remove all rules first
                if sg.get("IpPermissions"):
                    try:
                        ec2_client.revoke_security_group_ingress(
                            GroupId=sg_id,
                            IpPermissions=sg["IpPermissions"]
                        )
                        logger.info(f"  ✓ Removed inbound rules from {sg_name}")
                    except ClientError as e:
                        if e.response.get("Error", {}).get("Code") != "InvalidPermission.NotFound":
                            logger.debug(f"    Could not remove inbound rules: {e}")
                
                if sg.get("IpPermissionsEgress"):
                    egress_rules = [r for r in sg["IpPermissionsEgress"] 
                                   if not (r.get("IpProtocol") == "-1" and 
                                          len(r.get("IpRanges", [])) == 1 and
                                          r["IpRanges"][0].get("CidrIp") == "0.0.0.0/0")]
                    if egress_rules:
                        try:
                            ec2_client.revoke_security_group_egress(
                                GroupId=sg_id,
                                IpPermissions=egress_rules
                            )
                            logger.info(f"  ✓ Removed outbound rules from {sg_name}")
                        except ClientError as e:
                            if e.response.get("Error", {}).get("Code") != "InvalidPermission.NotFound":
                                logger.debug(f"    Could not remove outbound rules: {e}")
                
                # Check for network interfaces and delete if available
                try:
                    enis = ec2_client.describe_network_interfaces(
                        Filters=[{"Name": "group-id", "Values": [sg_id]}]
                    )
                    for eni in enis.get("NetworkInterfaces", []):
                        if eni["Status"] == "available":
                            try:
                                ec2_client.delete_network_interface(NetworkInterfaceId=eni["NetworkInterfaceId"])
                                logger.info(f"  ✓ Deleted network interface: {eni['NetworkInterfaceId']}")
                            except:
                                pass
                except Exception as e:
                    logger.debug(f"    Could not check network interfaces: {e}")
                
                time.sleep(10)
                
                # Try to delete the security group with retry
                deleted = False
                for attempt in range(3):
                    try:
                        ec2_client.delete_security_group(GroupId=sg_id)
                        logger.info(f"  ✓ Deleted security group: {sg_name} ({sg_id})")
                        deleted = True
                        break
                    except ClientError as e:
                        if e.response["Error"]["Code"] == "InvalidGroup.NotFound":
                            logger.info(f"  Security group {sg_name} ({sg_id}) already deleted")
                            deleted = True
                            break
                        elif attempt < 2:
                            logger.info(f"  Retrying security group deletion in 15 seconds...")
                            time.sleep(15)
                        else:
                            logger.warning(f"  Could not delete security group {sg_name} ({sg_id}): {e}")
                
                if not deleted:
                    logger.warning(f"  ⚠ Failed to delete security group: {sg_name} ({sg_id})")
                    
            except ClientError as e:
                if e.response["Error"]["Code"] == "InvalidGroupId.NotFound":
                    logger.debug(f"  Security group {sg_name} ({sg_id}) not found (already deleted)")
                else:
                    logger.warning(f"  Error processing security group {sg_name} ({sg_id}): {e}")
            except Exception as e:
                logger.warning(f"  Error force deleting security group {sg_name} ({sg_id}): {e}")
        
        logger.info("✓ Force delete security groups completed")
    except Exception as e:
        logger.debug(f"Error in force delete specific security group: {e}")

def force_delete_specific_vpc():
    """Force delete the specific VPC that's having issues."""
    logger.info("Attempting to force delete specific VPC...")
    
    vpc_id = "vpc-07bc97e641ca53b3c"  # The VPC we found earlier
    
    try:
        # Check if VPC still exists
        vpcs = ec2_client.describe_vpcs(VpcIds=[vpc_id])
        if not vpcs.get("Vpcs"):
            logger.info(f"  VPC {vpc_id} already deleted")
            return True
        
        logger.info(f"  Found VPC to delete: {vpc_id}")
        
        # Force delete with comprehensive cleanup
        return delete_single_vpc(vpc_id)
    except ClientError as e:
        if e.response["Error"]["Code"] == "InvalidVpcID.NotFound":
            logger.info(f"  VPC {vpc_id} already deleted")
            return True
        else:
            logger.error(f"  Error checking VPC {vpc_id}: {e}")
            return False

def delete_iam_roles():
    """Delete IAM roles and policies."""
    logger.info("[7/9] Deleting IAM roles")
    
    role_names = [
        f"role-knowledge-base-for-{project_name}-{region}",
        f"role-agent-for-{project_name}-{region}",
        f"role-ec2-for-{project_name}-{region}",
        f"role-lambda-rag-for-{project_name}-{region}",
        f"role-agentcore-memory-for-{project_name}-{region}"
    ]
    
    for role_name in role_names:
        try:
            # Detach managed policies
            attached_policies = iam_client.list_attached_role_policies(RoleName=role_name)
            for policy in attached_policies["AttachedPolicies"]:
                iam_client.detach_role_policy(
                    RoleName=role_name,
                    PolicyArn=policy["PolicyArn"]
                )
            
            # Delete inline policies
            inline_policies = iam_client.list_role_policies(RoleName=role_name)
            for policy_name in inline_policies["PolicyNames"]:
                iam_client.delete_role_policy(
                    RoleName=role_name,
                    PolicyName=policy_name
                )
            
            # Remove from instance profile if exists
            instance_profile_name = f"instance-profile-{project_name}-{region}"
            try:
                iam_client.remove_role_from_instance_profile(
                    InstanceProfileName=instance_profile_name,
                    RoleName=role_name
                )
            except:
                pass
            
            # Delete role
            iam_client.delete_role(RoleName=role_name)
            logger.info(f"  ✓ Deleted role: {role_name}")
        except ClientError as e:
            if e.response["Error"]["Code"] != "NoSuchEntity":
                logger.warning(f"  Could not delete role {role_name}: {e}")
    
    # Delete instance profile
    try:
        instance_profile_name = f"instance-profile-{project_name}-{region}"
        iam_client.delete_instance_profile(InstanceProfileName=instance_profile_name)
        logger.info(f"  ✓ Deleted instance profile: {instance_profile_name}")
    except ClientError as e:
        if e.response["Error"]["Code"] != "NoSuchEntity":
            logger.warning(f"  Could not delete instance profile: {e}")
    
    logger.info("✓ IAM roles deleted")

def delete_s3_buckets():
    """Delete S3 buckets and all objects."""
    logger.info("[8/9] Deleting S3 buckets")
    
    # List of possible bucket names
    bucket_names = [
        bucket_name,  # storage-for-mcp-{account_id}-{region}
        f"storage-for-{project_name}--{region}"  # storage-for-mcp--us-west-2 (when account_id is empty)
    ]
    
    for bucket in bucket_names:
        try:
            # Delete all objects and versions
            try:
                # List and delete all object versions
                versions = s3_client.list_object_versions(Bucket=bucket)
                delete_keys = []
                
                # Add current versions
                if "Versions" in versions:
                    for version in versions["Versions"]:
                        delete_keys.append({
                            "Key": version["Key"],
                            "VersionId": version["VersionId"]
                        })
                
                # Add delete markers
                if "DeleteMarkers" in versions:
                    for marker in versions["DeleteMarkers"]:
                        delete_keys.append({
                            "Key": marker["Key"],
                            "VersionId": marker["VersionId"]
                        })
                
                # Delete in batches of 1000
                if delete_keys:
                    for i in range(0, len(delete_keys), 1000):
                        batch = delete_keys[i:i+1000]
                        s3_client.delete_objects(
                            Bucket=bucket,
                            Delete={"Objects": batch}
                        )
                    logger.info(f"  ✓ Deleted {len(delete_keys)} objects/versions from {bucket}")
                
            except ClientError as e:
                if e.response["Error"]["Code"] != "NoSuchBucket":
                    logger.warning(f"  Could not delete objects from {bucket}: {e}")
            
            # Delete bucket
            s3_client.delete_bucket(Bucket=bucket)
            logger.info(f"  ✓ Deleted bucket: {bucket}")
            
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchBucket":
                logger.info(f"  Bucket {bucket} does not exist")
            else:
                logger.warning(f"  Could not delete bucket {bucket}: {e}")
    
    logger.info("✓ S3 buckets deleted")

def retry_vpc_deletion():
    """Retry VPC deletion after CloudFront distributions are fully deleted."""
    logger.info("[9/9] Retrying VPC deletion after CloudFront cleanup")
    
    try:
        # Find VPCs that still exist and match our project
        vpc_name = f"vpc-for-{project_name}"
        
        # Check by tag name
        vpcs_by_tag = ec2_client.describe_vpcs(
            Filters=[{"Name": "tag:Name", "Values": [vpc_name]}]
        )
        
        vpcs_to_retry = []
        for vpc in vpcs_by_tag.get("Vpcs", []):
            vpc_id = vpc["VpcId"]
            vpcs_to_retry.append(vpc_id)
            logger.info(f"  Found VPC to retry deletion: {vpc_id}")
        
        if not vpcs_to_retry:
            logger.info("  No VPCs found to retry deletion")
            return
        
        # Retry deletion for each VPC
        for vpc_id in vpcs_to_retry:
            logger.info(f"  Retrying deletion for VPC: {vpc_id}")
            delete_single_vpc(vpc_id)
        
        logger.info("✓ VPC deletion retry completed")
    except Exception as e:
        logger.error(f"Error during VPC deletion retry: {e}")

def main():
    """Main function to delete all infrastructure."""
    logger.info("="*60)
    logger.info("Starting AWS Infrastructure Cleanup")
    logger.info("="*60)
    logger.info(f"Project: {project_name}")
    logger.info(f"Region: {region}")
    logger.info(f"Account ID: {account_id}")
    logger.info("="*60)
    
    start_time = time.time()
    
    try:
        delete_cloudfront_distributions()
        delete_alb_resources()
        delete_ec2_instances()
        delete_nat_gateways()
        
        # Wait for VPC endpoints to be deleted first
        wait_for_vpc_endpoint_deletion()
        delete_vpc_endpoints_and_wait()
        
        delete_security_groups()
        delete_route_tables()
        
        failed_vpcs = delete_vpc_resources()
        
        delete_opensearch_collection()
        delete_knowledge_bases()
        # delete_code_interpreters()
        delete_secrets()
        delete_iam_roles()
        delete_s3_buckets()
        delete_disabled_cloudfront_distributions()
        
        # Retry VPC deletion only if there were failures
        if failed_vpcs:
            logger.info(f"  VPC deletion failed for {len(failed_vpcs)} VPC(s): {failed_vpcs}")
            logger.info("  Retrying VPC deletion after CloudFront cleanup...")
            retry_vpc_deletion()
        
        elapsed_time = time.time() - start_time
        logger.info("")
        logger.info("="*60)
        logger.info("Infrastructure Cleanup Completed Successfully!")
        logger.info("="*60)
        logger.info(f"Total cleanup time: {elapsed_time/60:.2f} minutes")
        logger.info("="*60)
        
    except Exception as e:
        elapsed_time = time.time() - start_time
        logger.error("")
        logger.error("="*60)
        logger.error("Cleanup Failed!")
        logger.error("="*60)
        logger.error(f"Error: {e}")
        logger.error(f"Cleanup time before failure: {elapsed_time/60:.2f} minutes")
        logger.error("="*60)
        import traceback
        logger.error(traceback.format_exc())
        raise

if __name__ == "__main__":
    main()

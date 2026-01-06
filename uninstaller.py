#!/usr/bin/env python3
"""
AWS Infrastructure Uninstaller
This script deletes all AWS infrastructure resources created by installer.py.
"""

import boto3
import json
import os
import time
import logging
from datetime import datetime
from typing import Dict, List, Optional
from botocore.exceptions import ClientError

# Configuration
project_name = "mcp"
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
sts_client = boto3.client("sts", region_name=region)
bedrock_agent_client = boto3.client("bedrock-agent", region_name=region)

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

def delete_single_vpc(vpc_id: str):
    """Delete a single VPC and all its related resources."""
    logger.info(f"  Deleting VPC: {vpc_id}")
    
    try:
        # Delete VPC endpoints first - force deletion using AWS CLI if boto3 fails
        try:
            endpoints = ec2_client.describe_vpc_endpoints(
                Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
            )
            for endpoint in endpoints["VpcEndpoints"]:
                if endpoint["State"] not in ["deleted", "deleting"]:
                    endpoint_id = endpoint["VpcEndpointId"]
                    try:
                        # Try using AWS CLI as fallback
                        import subprocess
                        result = subprocess.run([
                            "aws", "ec2", "delete-vpc-endpoints", 
                            "--vpc-endpoint-ids", endpoint_id,
                            "--region", region
                        ], capture_output=True, text=True)
                        
                        if result.returncode == 0:
                            logger.info(f"    ✓ Deleted VPC endpoint: {endpoint_id}")
                        else:
                            logger.warning(f"    Could not delete VPC endpoint {endpoint_id}: {result.stderr}")
                    except Exception as endpoint_error:
                        logger.warning(f"    Could not delete VPC endpoint {endpoint_id}: {endpoint_error}")
            
            # Wait longer for VPC endpoints to be deleted
            if endpoints["VpcEndpoints"]:
                logger.info("    Waiting for VPC endpoints to be deleted...")
                time.sleep(60)
        except Exception as e:
            logger.info(f"    Skipping VPC endpoint cleanup: {e}")
        
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
        
        # Delete NAT gateways
        nat_gws = ec2_client.describe_nat_gateways(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )
        for nat_gw in nat_gws["NatGateways"]:
            if nat_gw["State"] != "deleted":
                ec2_client.delete_nat_gateway(NatGatewayId=nat_gw["NatGatewayId"])
                logger.info(f"    ✓ Deleted NAT Gateway: {nat_gw['NatGatewayId']}")
        
        # Wait for NAT gateways to be deleted
        time.sleep(30)
        
        # Release Elastic IPs
        eips = ec2_client.describe_addresses()
        for eip in eips["Addresses"]:
            if "NetworkInterfaceId" not in eip and "InstanceId" not in eip:
                try:
                    ec2_client.release_address(AllocationId=eip["AllocationId"])
                    logger.info(f"    ✓ Released EIP: {eip['AllocationId']}")
                except:
                    pass
        
        # Delete security groups
        sgs = ec2_client.describe_security_groups(
            Filters=[{"Name": "vpc-id", "Values": [vpc_id]}]
        )
        for sg in sgs["SecurityGroups"]:
            if sg["GroupName"] != "default":
                try:
                    ec2_client.delete_security_group(GroupId=sg["GroupId"])
                    logger.info(f"    ✓ Deleted security group: {sg['GroupId']}")
                except:
                    pass
        
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
        for attempt in range(3):
            try:
                ec2_client.delete_vpc(VpcId=vpc_id)
                logger.info(f"  ✓ Deleted VPC: {vpc_id}")
                break
            except ClientError as e:
                if e.response["Error"]["Code"] == "DependencyViolation":
                    if attempt < 2:
                        logger.info(f"    VPC has dependencies, cleaning up remaining resources (attempt {attempt + 1}/3)...")
                        
                        # Additional cleanup for remaining dependencies
                        try:
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
                            
                            # Delete any remaining DHCP options
                            dhcp_options = ec2_client.describe_dhcp_options()
                            for dhcp in dhcp_options["DhcpOptions"]:
                                try:
                                    ec2_client.disassociate_dhcp_options(VpcId=vpc_id)
                                    break
                                except:
                                    pass
                        except:
                            pass
                        
                        time.sleep(30)
                    else:
                        logger.warning(f"  Could not delete VPC {vpc_id}: {e}")
                        break
                else:
                    logger.warning(f"  Could not delete VPC {vpc_id}: {e}")
                    break
        
        logger.info(f"  ✓ VPC {vpc_id} deleted")
    except Exception as e:
        logger.error(f"Error deleting VPC {vpc_id}: {e}")

def delete_vpc_resources():
    """Delete VPC and related resources."""
    logger.info("[4/9] Deleting VPC resources")
    
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
            delete_single_vpc(vpc_id)
        
        logger.info("✓ VPC resources deleted")
    except Exception as e:
        logger.error(f"Error deleting VPC resources: {e}")

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
            ("network", f"network-{project_name}-{region}"),
            ("encryption", f"encription-{project_name}-{region}")
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
        delete_vpc_resources()
        delete_opensearch_collection()
        delete_knowledge_bases()
        delete_secrets()
        delete_iam_roles()
        delete_s3_buckets()
        delete_disabled_cloudfront_distributions()
        
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

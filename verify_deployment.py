#!/usr/bin/env python3
"""
Quick script to verify EC2 deployment in private subnets
"""

import boto3
import json

# Configuration
project_name = "mcp"
region = "us-west-2"

# Initialize boto3 clients
ec2_client = boto3.client("ec2", region_name=region)

def verify_deployment():
    """Verify that EC2 instances are deployed in private subnets."""
    print("="*60)
    print("EC2 Subnet Deployment Verification")
    print("="*60)
    
    instance_name = f"app-for-{project_name}"
    
    try:
        instances = ec2_client.describe_instances(
            Filters=[
                {"Name": "tag:Name", "Values": [instance_name]},
                {"Name": "instance-state-name", "Values": ["running", "pending", "stopping", "stopped"]}
            ]
        )
        
        if not instances["Reservations"]:
            print(f"❌ No EC2 instances found with name: {instance_name}")
            return
        
        for reservation in instances["Reservations"]:
            for instance in reservation["Instances"]:
                instance_id = instance["InstanceId"]
                subnet_id = instance["SubnetId"]
                vpc_id = instance["VpcId"]
                has_public_ip = instance.get("PublicIpAddress") is not None
                private_ip = instance["PrivateIpAddress"]
                state = instance["State"]["Name"]
                
                print(f"\n🖥️  Instance: {instance_id}")
                print(f"   State: {state}")
                print(f"   VPC: {vpc_id}")
                print(f"   Subnet: {subnet_id}")
                print(f"   Private IP: {private_ip}")
                print(f"   Has Public IP: {has_public_ip}")
                
                # Check subnet details
                subnet_details = ec2_client.describe_subnets(SubnetIds=[subnet_id])
                subnet = subnet_details["Subnets"][0]
                cidr_block = subnet["CidrBlock"]
                az = subnet["AvailabilityZone"]
                map_public_ip = subnet["MapPublicIpOnLaunch"]
                
                print(f"   Subnet CIDR: {cidr_block}")
                print(f"   Availability Zone: {az}")
                print(f"   Auto-assign Public IP: {map_public_ip}")
                
                # Check subnet type from tags
                is_private_subnet = False
                subnet_type = "Unknown"
                for tag in subnet.get("Tags", []):
                    if tag["Key"] == "aws-cdk:subnet-type":
                        subnet_type = tag["Value"]
                        is_private_subnet = (tag["Value"] == "Private")
                        break
                    elif tag["Key"] == "Name" and "private" in tag["Value"].lower():
                        is_private_subnet = True
                        subnet_type = "Private (inferred from name)"
                        break
                    elif tag["Key"] == "Name" and "public" in tag["Value"].lower():
                        subnet_type = "Public (inferred from name)"
                        break
                
                # If no explicit tag, check route table for internet gateway
                if subnet_type == "Unknown":
                    route_tables = ec2_client.describe_route_tables(
                        Filters=[{"Name": "association.subnet-id", "Values": [subnet_id]}]
                    )
                    has_igw_route = False
                    for rt in route_tables["RouteTables"]:
                        for route in rt["Routes"]:
                            if (route.get("GatewayId", "").startswith("igw-") and 
                                route.get("DestinationCidrBlock") == "0.0.0.0/0"):
                                has_igw_route = True
                                break
                        if has_igw_route:
                            break
                    
                    if has_igw_route:
                        subnet_type = "Public (has IGW route)"
                        is_private_subnet = False
                    else:
                        subnet_type = "Private (no IGW route)"
                        is_private_subnet = True
                
                print(f"   Subnet Type: {subnet_type}")
                
                # Security assessment
                print(f"\n🔒 Security Assessment:")
                if is_private_subnet and not has_public_ip:
                    print(f"   ✅ SECURE: Instance is in private subnet without public IP")
                elif is_private_subnet and has_public_ip:
                    print(f"   ⚠️  WARNING: Instance is in private subnet but has public IP")
                elif not is_private_subnet and not has_public_ip:
                    print(f"   ⚠️  WARNING: Instance is in public subnet (but no public IP assigned)")
                else:
                    print(f"   ❌ INSECURE: Instance is in public subnet with public IP")
                    print(f"   🚨 RECOMMENDATION: Move to private subnet for better security")
                
                print("-" * 60)
        
    except Exception as e:
        print(f"❌ Error verifying deployment: {e}")

if __name__ == "__main__":
    verify_deployment()

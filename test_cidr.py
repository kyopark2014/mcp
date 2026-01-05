#!/usr/bin/env python3
"""
Test script to verify CIDR conflict detection
"""

import boto3

# Initialize boto3 client
ec2_client = boto3.client("ec2", region_name="us-west-2")

def get_available_cidr_block() -> str:
    """Get an available CIDR block that doesn't conflict with existing VPCs."""
    # Candidate CIDR blocks to try
    candidate_cidrs = [
        "10.20.0.0/16",
        "10.21.0.0/16", 
        "10.22.0.0/16",
        "10.23.0.0/16",
        "10.24.0.0/16",
        "172.16.0.0/16",
        "172.17.0.0/16",
        "172.18.0.0/16",
        "192.168.0.0/16"
    ]
    
    # Get all existing VPC CIDR blocks
    existing_cidrs = set()
    try:
        vpcs = ec2_client.describe_vpcs()
        for vpc in vpcs["Vpcs"]:
            existing_cidrs.add(vpc["CidrBlock"])
            # Also check additional CIDR blocks
            for cidr_assoc in vpc.get("CidrBlockAssociationSet", []):
                existing_cidrs.add(cidr_assoc["CidrBlock"])
    except Exception as e:
        print(f"Could not check existing VPCs: {e}")
    
    print("Existing VPC CIDR blocks:")
    for cidr in sorted(existing_cidrs):
        print(f"  - {cidr}")
    
    # Find first available CIDR
    for cidr in candidate_cidrs:
        if cidr not in existing_cidrs:
            print(f"\n✅ Available CIDR block: {cidr}")
            return cidr
    
    # Fallback - this should rarely happen
    print("\n⚠️  All candidate CIDR blocks are in use, using 10.25.0.0/16")
    return "10.25.0.0/16"

if __name__ == "__main__":
    print("="*50)
    print("CIDR Conflict Detection Test")
    print("="*50)
    get_available_cidr_block()

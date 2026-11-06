"""Render the exact resource proposal offline. Network creation is a separate decision."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from plan import ACCOUNT, BUCKET, REGION, SECRETS, SERVICE


def template() -> dict:
    tags = [
        {"Key": k, "Value": v}
        for k, v in {
            "app": "mission-control",
            "application": "ai-engineer",
            "sprint": "materialization-observation-2026-10",
        }.items()
    ]
    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Principal": {"Service": "ecs-tasks.amazonaws.com"},
                "Action": "sts:AssumeRole",
            }
        ],
    }
    bucket_arn = f"arn:aws:s3:::{BUCKET}"
    storage = {
        "Version": "2012-10-17",
        "Statement": [
            {"Effect": "Allow", "Action": ["s3:ListBucket"], "Resource": bucket_arn},
            {
                "Effect": "Allow",
                "Action": ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"],
                "Resource": bucket_arn + "/*",
            },
        ],
    }
    resources = {
        "Repository": {
            "Type": "AWS::ECR::Repository",
            "Properties": {
                "RepositoryName": "mission-control-worker",
                "ImageTagMutability": "IMMUTABLE",
                "ImageScanningConfiguration": {"ScanOnPush": True},
                "Tags": tags,
                "LifecyclePolicy": {
                    "LifecyclePolicyText": json.dumps(
                        {
                            "rules": [
                                {
                                    "rulePriority": 1,
                                    "description": "Retain last ten images",
                                    "selection": {
                                        "tagStatus": "any",
                                        "countType": "imageCountMoreThan",
                                        "countNumber": 10,
                                    },
                                    "action": {"type": "expire"},
                                }
                            ]
                        }
                    )
                },
            },
        },
        "Payloads": {
            "Type": "AWS::S3::Bucket",
            "DeletionPolicy": "Retain",
            "UpdateReplacePolicy": "Retain",
            "Properties": {
                "BucketName": BUCKET,
                "Tags": tags,
                "PublicAccessBlockConfiguration": dict.fromkeys(
                    (
                        "BlockPublicAcls",
                        "BlockPublicPolicy",
                        "IgnorePublicAcls",
                        "RestrictPublicBuckets",
                    ),
                    True,
                ),
                "OwnershipControls": {"Rules": [{"ObjectOwnership": "BucketOwnerEnforced"}]},
                "BucketEncryption": {
                    "ServerSideEncryptionConfiguration": [
                        {"ServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}
                    ]
                },
            },
        },
        "ExecutionRole": {
            "Type": "AWS::IAM::Role",
            "Properties": {
                "RoleName": SERVICE + "-exec",
                "AssumeRolePolicyDocument": trust,
                "Tags": tags,
                "ManagedPolicyArns": [
                    "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
                ],
                "Policies": [
                    {
                        "PolicyName": "ApplicationSecrets",
                        "PolicyDocument": {
                            "Version": "2012-10-17",
                            "Statement": [
                                {
                                    "Effect": "Allow",
                                    "Action": ["secretsmanager:GetSecretValue"],
                                    "Resource": (
                                        f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:"
                                        "secret:mission-control/ai-engineer/*"
                                    ),
                                }
                            ],
                        },
                    }
                ],
            },
        },
        "TaskRole": {
            "Type": "AWS::IAM::Role",
            "Properties": {
                "RoleName": SERVICE + "-task",
                "AssumeRolePolicyDocument": trust,
                "Tags": tags,
                "Policies": [{"PolicyName": "ApplicationPayloads", "PolicyDocument": storage}],
            },
        },
        "LocalPayloadUser": {
            "Type": "AWS::IAM::User",
            "Properties": {
                "UserName": "mission-control-local-ai-engineer",
                "Tags": tags,
                "Policies": [{"PolicyName": "ApplicationPayloads", "PolicyDocument": storage}],
            },
        },
        "Logs": {
            "Type": "AWS::Logs::LogGroup",
            "Properties": {
                "LogGroupName": "/mission-control/ai-engineer/worker",
                "RetentionInDays": 14,
                "Tags": tags,
            },
        },
        "Cluster": {
            "Type": "AWS::ECS::Cluster",
            "Properties": {
                "ClusterName": "mission-control",
                "CapacityProviders": ["FARGATE"],
                "Tags": tags,
            },
        },
        "Egress": {
            "Type": "AWS::EC2::SecurityGroup",
            "Properties": {
                "GroupName": "mc-worker-egress-only",
                "GroupDescription": "Mission Control outbound worker",
                "VpcId": {"Ref": "VpcId"},
                "SecurityGroupIngress": [],
                "SecurityGroupEgress": [{"IpProtocol": "-1", "CidrIp": "0.0.0.0/0"}],
                "Tags": tags,
            },
        },
        "Budget": {
            "Type": "AWS::Budgets::Budget",
            "Properties": {
                "Budget": {
                    "BudgetName": "mission-control-monthly",
                    "BudgetType": "COST",
                    "TimeUnit": "MONTHLY",
                    "BudgetLimit": {"Amount": 40, "Unit": "USD"},
                },
                "NotificationsWithSubscribers": [
                    {
                        "Notification": {
                            "NotificationType": kind,
                            "ComparisonOperator": "GREATER_THAN",
                            "Threshold": threshold,
                            "ThresholdType": "PERCENTAGE",
                        },
                        "Subscribers": [
                            {"SubscriptionType": "EMAIL", "Address": {"Ref": "BudgetEmail"}}
                        ],
                    }
                    for kind, threshold in (("ACTUAL", 80), ("FORECASTED", 100))
                ],
            },
        },
    }
    for index, name in enumerate(sorted(SECRETS)):
        resources[f"Secret{index}"] = {
            "Type": "AWS::SecretsManager::Secret",
            "DeletionPolicy": "Retain",
            "UpdateReplacePolicy": "Retain",
            "Properties": {
                "Name": f"mission-control/ai-engineer/{name}",
                "Description": "Owner supplies the value after resource review",
                "Tags": tags,
            },
        }
    return {
        "AWSTemplateFormatVersion": "2010-09-09",
        "Description": (
            "Run 2 exact AI Engineer resources. No service or secret values created by rendering."
        ),
        "Parameters": {
            "VpcId": {"Type": "AWS::EC2::VPC::Id"},
            "BudgetEmail": {"Type": "String", "AllowedPattern": r"[^@\s]+@[^@\s]+\.[^@\s]+"},
        },
        "Resources": resources,
        "Outputs": {"WorkerSecurityGroup": {"Value": {"Ref": "Egress"}}},
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    args.out.write_text(json.dumps(template(), indent=2) + "\n")

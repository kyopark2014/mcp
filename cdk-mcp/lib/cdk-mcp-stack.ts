import * as cdk from 'aws-cdk-lib';
import { Construct } from 'constructs';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as secretsmanager from 'aws-cdk-lib/aws-secretsmanager';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as opensearchserverless from 'aws-cdk-lib/aws-opensearchserverless';
import * as cloudFront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as path from "path";
import * as ec2 from 'aws-cdk-lib/aws-ec2';
import * as elbv2 from 'aws-cdk-lib/aws-elasticloadbalancingv2';
import * as elbv2_tg from 'aws-cdk-lib/aws-elasticloadbalancingv2-targets'

const projectName = `mcp`; 
const region = process.env.CDK_DEFAULT_REGION;    
const accountId = process.env.CDK_DEFAULT_ACCOUNT;
const bucketName = `storage-for-${projectName}-${accountId}-${region}`; 
const vectorIndexName = projectName

export class CdkMcpStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // s3 
    const s3Bucket = new s3.Bucket(this, `storage-${projectName}`,{
      bucketName: bucketName,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      publicReadAccess: false,
      versioned: false,
      cors: [
        {
          allowedHeaders: ['*'],
          allowedMethods: [
            s3.HttpMethods.GET,
            s3.HttpMethods.POST,
            s3.HttpMethods.PUT,
          ],
          allowedOrigins: ['*'],
        },
      ],
    });
    new cdk.CfnOutput(this, 'bucketName', {
      value: s3Bucket.bucketName,
      description: 'The nmae of bucket',
    });

    // Knowledge Base Role
    const knowledge_base_role = new iam.Role(this,  `role-knowledge-base-for-${projectName}`, {
      roleName: `role-knowledge-base-for-${projectName}-${region}`,
      assumedBy: new iam.CompositePrincipal(
        new iam.ServicePrincipal("bedrock.amazonaws.com")
      )
    });
    
    const bedrockInvokePolicy = new iam.PolicyStatement({ 
      effect: iam.Effect.ALLOW,
      resources: [`*`],
      actions: ["bedrock:*"],
    });        
    knowledge_base_role.attachInlinePolicy( 
      new iam.Policy(this, `bedrock-invoke-policy-for-${projectName}`, {
        statements: [bedrockInvokePolicy],
      }),
    );  
    
    const bedrockKnowledgeBaseS3Policy = new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      resources: ['*'],
      actions: ["s3:*"],
    });
    knowledge_base_role.attachInlinePolicy( 
      new iam.Policy(this, `knowledge-base-s3-policy-for-${projectName}`, {
        statements: [bedrockKnowledgeBaseS3Policy],
      }),
    );      
    const knowledgeBaseOpenSearchPolicy = new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      resources: ['*'],
      actions: ["aoss:APIAccessAll"],
    });
    knowledge_base_role.attachInlinePolicy( 
      new iam.Policy(this, `bedrock-agent-opensearch-policy-for-${projectName}`, {
        statements: [knowledgeBaseOpenSearchPolicy],
      }),
    );  

    const knowledgeBaseBedrockPolicy = new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      resources: ['*'],
      actions: ["bedrock:*"],
    });
    knowledge_base_role.attachInlinePolicy( 
      new iam.Policy(this, `bedrock-agent-bedrock-policy-for-${projectName}`, {
        statements: [knowledgeBaseBedrockPolicy],
      }),
    );  

    // OpenSearch Serverless
    const collectionName = vectorIndexName
    const OpenSearchCollection = new opensearchserverless.CfnCollection(this, `opensearch-correction-for-${projectName}`, {
      name: collectionName,    
      description: `opensearch correction for ${projectName}`,
      standbyReplicas: 'DISABLED',
      type: 'VECTORSEARCH',
    });
    const collectionArn = OpenSearchCollection.attrArn

    new cdk.CfnOutput(this, `OpensearchCollectionEndpoint-${projectName}`, {
      value: OpenSearchCollection.attrCollectionEndpoint,
      description: 'The endpoint of opensearch correction',
    });

    const encPolicyName = `encription-${projectName}-${region}`
    const encPolicy = new opensearchserverless.CfnSecurityPolicy(this, `opensearch-encription-policy-for-${projectName}`, {
      name: encPolicyName,
      type: "encryption",
      description: `opensearch encryption policy for ${projectName}`,
      policy:
        `{"Rules":[{"ResourceType":"collection","Resource":["collection/${collectionName}"]}],"AWSOwnedKey":true}`,
    });
    OpenSearchCollection.addDependency(encPolicy);

    const netPolicyName = `network-${projectName}-${region}`
    const netPolicy = new opensearchserverless.CfnSecurityPolicy(this, `opensearch-network-policy-for-${projectName}`, {
      name: netPolicyName,
      type: 'network',    
      description: `opensearch network policy for ${projectName}`,
      policy: JSON.stringify([
        {
          Rules: [
            {
              ResourceType: "dashboard",
              Resource: [`collection/${collectionName}`],
            },
            {
              ResourceType: "collection",
              Resource: [`collection/${collectionName}`],              
            }
          ],
          AllowFromPublic: true,          
        },
      ]), 
    });
    OpenSearchCollection.addDependency(netPolicy);

    const account = new iam.AccountPrincipal(this.account)
    const dataAccessPolicyName = `data-${projectName}`
    const dataAccessPolicy = new opensearchserverless.CfnAccessPolicy(this, `opensearch-data-collection-policy-for-${projectName}`, {
      name: dataAccessPolicyName,
      type: "data",
      policy: JSON.stringify([
        {
          Rules: [
            {
              Resource: [`collection/${collectionName}`],
              Permission: [
                "aoss:CreateCollectionItems",
                "aoss:DeleteCollectionItems",
                "aoss:UpdateCollectionItems",
                "aoss:DescribeCollectionItems",
              ],
              ResourceType: "collection",
            },
            {
              Resource: [`index/${collectionName}/*`],
              Permission: [
                "aoss:CreateIndex",
                "aoss:DeleteIndex",
                "aoss:UpdateIndex",
                "aoss:DescribeIndex",
                "aoss:ReadDocument",
                "aoss:WriteDocument",
              ], 
              ResourceType: "index",
            }
          ],
          Principal: [
            account.arn
          ], 
        },
      ]),
    });
    OpenSearchCollection.addDependency(dataAccessPolicy);

    // agent role
    const agent_role = new iam.Role(this,  `role-agent-for-${projectName}`, {
      roleName: `role-agent-for-${projectName}-${region}`,
      assumedBy: new iam.CompositePrincipal(
        new iam.ServicePrincipal("bedrock.amazonaws.com")
      )
    });

    const bedrockRetrievePolicy = new iam.PolicyStatement({ 
      effect: iam.Effect.ALLOW,
      resources: [
        `arn:aws:bedrock:${region}:${accountId}:knowledge-base/*`
      ],
      actions: [
        "bedrock:Retrieve"
      ],
    });        
    agent_role.attachInlinePolicy( 
      new iam.Policy(this, `bedrock-retrieve-policy-for-${projectName}`, {
        statements: [bedrockRetrievePolicy],
      }),
    );  
    
    const agentInferencePolicy = new iam.PolicyStatement({ 
      effect: iam.Effect.ALLOW,
      resources: [
        `arn:aws:bedrock:${region}:${accountId}:inference-profile/*`,
        `arn:aws:bedrock:*::foundation-model/*`
      ],
      actions: [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream",
        "bedrock:GetInferenceProfile",
        "bedrock:GetFoundationModel"
      ],
    });        
    agent_role.attachInlinePolicy( 
      new iam.Policy(this, `agent-inference-policy-for-${projectName}`, {
        statements: [agentInferencePolicy],
      }),
    );  

    // Lambda Invoke
    agent_role.addToPolicy(new iam.PolicyStatement({
      resources: ['*'],
      actions: [
        'lambda:InvokeFunction',
        'cloudwatch:*'
      ]
    }));
    agent_role.addManagedPolicy({
      managedPolicyArn: 'arn:aws:iam::aws:policy/AWSLambdaExecute',
    });

    // EC2 Role
    const ec2Role = new iam.Role(this, `role-ec2-for-${projectName}`, {
      roleName: `role-ec2-for-${projectName}-${region}`,
      assumedBy: new iam.CompositePrincipal(
        new iam.ServicePrincipal("ec2.amazonaws.com"),
        new iam.ServicePrincipal("bedrock.amazonaws.com"),
      ),
      managedPolicies: [cdk.aws_iam.ManagedPolicy.fromAwsManagedPolicyName('CloudWatchAgentServerPolicy')] 
    });

    const secreatManagerPolicy = new iam.PolicyStatement({  
      resources: ['*'],
      actions: ['secretsmanager:GetSecretValue'],
    });       
    ec2Role.attachInlinePolicy( // for isengard
      new iam.Policy(this, `secret-manager-policy-ec2-for-${projectName}`, {
        statements: [secreatManagerPolicy],
      }),
    );

    const pvrePolicy = new iam.PolicyStatement({  
      resources: ['*'],
      actions: ['ssm:*', 'ssmmessages:*', 'ec2messages:*', 'tag:*'],
    });       
    ec2Role.attachInlinePolicy( // for isengard
      new iam.Policy(this, `pvre-policy-ec2-for-${projectName}`, {
        statements: [pvrePolicy],
      }),
    );  

    // Bedrock
    const BedrockPolicy = new iam.PolicyStatement({  
      resources: ['*'],
      actions: ['bedrock:*'],
    });     
    agent_role.attachInlinePolicy( // add bedrock policy
      new iam.Policy(this, `bedrock-policy-agent-for-${projectName}`, {
        statements: [BedrockPolicy],
      }),
    );   
    ec2Role.attachInlinePolicy( // add bedrock policy
      new iam.Policy(this, `bedrock-policy-ec2-for-${projectName}`, {
        statements: [BedrockPolicy],
      }),
    ); 

    const weatherApiSecret = new secretsmanager.Secret(this, `weather-api-secret-for-${projectName}`, {
      description: 'secret for weather api key', // openweathermap
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      secretName: `openweathermap-${projectName}`,
      secretObjectValue: {
        project_name: cdk.SecretValue.unsafePlainText(projectName),
        weather_api_key: cdk.SecretValue.unsafePlainText(''),
      },
    });
    weatherApiSecret.grantRead(ec2Role) 

    // Secret
    const langsmithApiSecret = new secretsmanager.Secret(this, `langsmith-secret-for-${projectName}`, {
      description: 'secret for lamgsmith api key', // lamgsmith
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      secretName: `langsmithapikey-${projectName}`,
      secretObjectValue: {
        langchain_project: cdk.SecretValue.unsafePlainText(projectName),
        langsmith_api_key: cdk.SecretValue.unsafePlainText(''),
      }, 
    });
    langsmithApiSecret.grantRead(ec2Role) 

    const tavilyApiSecret = new secretsmanager.Secret(this, `tavily-secret-for-${projectName}`, {
      description: 'secret for tavily api key', // tavily
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      secretName: `tavilyapikey-${projectName}`,
      secretObjectValue: {
        project_name: cdk.SecretValue.unsafePlainText(projectName),
        tavily_api_key: cdk.SecretValue.unsafePlainText(''),
      },
    });
    tavilyApiSecret.grantRead(ec2Role) 

    const perplexityApiSecret = new secretsmanager.Secret(this, `perflexity-secret-for-${projectName}`, {
      description: 'secret for perflexity api key', // perplexity
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      secretName: `perplexityapikey-${projectName}`,
      secretObjectValue: {
        project_name: cdk.SecretValue.unsafePlainText(projectName),
        perplexity_api_key: cdk.SecretValue.unsafePlainText(''),
      },
    });
    perplexityApiSecret.grantRead(ec2Role) 

    const firecrawlApiSecret = new secretsmanager.Secret(this, `firecrawl-secret-for-${projectName}`, {
      description: 'secret for firecrawl api key', // firecrawl
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      secretName: `firecrawlapikey-${projectName}`,
      secretObjectValue: {
        project_name: cdk.SecretValue.unsafePlainText(projectName),
        firecrawl_api_key: cdk.SecretValue.unsafePlainText(''),
      },
    });
    firecrawlApiSecret.grantRead(ec2Role) 

    const codeInterpreterSecret = new secretsmanager.Secret(this, `code-interpreter-secret-for-${projectName}`, {
      description: 'secret for code interpreter api key', // code interpreter
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      secretName: `code-interpreter-${projectName}`,
      secretObjectValue: {
        project_name: cdk.SecretValue.unsafePlainText(projectName),
        code_interpreter_api_key: cdk.SecretValue.unsafePlainText(''),
        code_interpreter_id: cdk.SecretValue.unsafePlainText(''),
      },
    });
    codeInterpreterSecret.grantRead(ec2Role) 

    const novaActSecret = new secretsmanager.Secret(this, `nova-act-secret-for-${projectName}`, {
      description: 'secret for nova act api key', // nova act
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      secretName: `novaactapikey-${projectName}`,
      secretObjectValue: {
        project_name: cdk.SecretValue.unsafePlainText(projectName),
        nova_act_api_key: cdk.SecretValue.unsafePlainText(''),
      },
    });
    novaActSecret.grantRead(ec2Role) 

    // Cost Explorer Policy
    const costExplorerPolicy = new iam.PolicyStatement({  
      resources: ['*'],
      actions: ['ce:GetCostAndUsage'],
    });        
    ec2Role.attachInlinePolicy( // add costExplorerPolicy
      new iam.Policy(this, `cost-explorer-policy-for-${projectName}`, {
        statements: [costExplorerPolicy],
      }),
    );   

    const ec2Policy = new iam.PolicyStatement({  
      resources: ['*'],
      actions: ['ec2:*'],
    });
    ec2Role.attachInlinePolicy( // add bedrock policy
      new iam.Policy(this, `ec2-policy-for-${projectName}`, {
        statements: [ec2Policy],
      }),
    );

    // Lambda Invoke
    ec2Role.addToPolicy(new iam.PolicyStatement({
      resources: ['*'],
      actions: [
        'lambda:InvokeFunction'
      ]
    }));

    // add permission for DescribeFileSystems
    ec2Role.addToPolicy(new iam.PolicyStatement({
      resources: ['*'],
      actions: [
        'ec2:DescribeFileSystems',
        'elasticfilesystem:DescribeFileSystems'
      ]
    }));

    // pass role
    const passRoleResourceArn = knowledge_base_role.roleArn;
    const passRolePolicy = new iam.PolicyStatement({  
      resources: [passRoleResourceArn],      
      actions: ['iam:PassRole'],
    });      
    ec2Role.attachInlinePolicy( // add pass role policy
      new iam.Policy(this, `pass-role-for-${projectName}`, {
      statements: [passRolePolicy],
      }), 
    );  

    // aoss
    const aossRolePolicy = new iam.PolicyStatement({  
      resources: ['*'],      
      actions: ['aoss:*'],
    }); 
    ec2Role.attachInlinePolicy( 
      new iam.Policy(this, `aoss-policy-for-${projectName}`, {
        statements: [aossRolePolicy],
      }),
    ); 

    // getRole
    const getRolePolicy = new iam.PolicyStatement({  
      resources: ['*'],      
      actions: ['iam:GetRole'],
    }); 
    ec2Role.attachInlinePolicy( 
      new iam.Policy(this, `getRole-policy-for-${projectName}`, {
        statements: [getRolePolicy],
      }),
    ); 

    // S3 Bucket Access
    const s3BucketAccessPolicy = new iam.PolicyStatement({
      resources: [`*`],
      actions: ['s3:*'],
    });
    ec2Role.attachInlinePolicy(
      new iam.Policy(this, `s3-bucket-access-policy-for-${projectName}`, {
        statements: [s3BucketAccessPolicy],
      }),
    );

    // CloudWatch Logs 
    const cloudWatchLogsPolicy = new iam.PolicyStatement({
      resources: ['*'],
      actions: [
        'logs:DescribeLogGroups',
        'logs:DescribeLogStreams',
        'logs:GetLogEvents',
        'logs:FilterLogEvents',
        'logs:GetLogGroupFields',
        'logs:GetLogRecord',
        'logs:GetQueryResults',
        'logs:StartQuery',
        'logs:StopQuery'
      ],
    });
    ec2Role.attachInlinePolicy(
      new iam.Policy(this, `cloudwatch-logs-policy-for-${projectName}`, {
        statements: [cloudWatchLogsPolicy],
      }),
    );

    // VPC
    const vpc = new ec2.Vpc(this, `vpc-for-${projectName}`, {
      vpcName: `vpc-for-${projectName}`,
      maxAzs: 2,
      ipAddresses: ec2.IpAddresses.cidr("10.20.0.0/16"),
      natGateways: 1,
      createInternetGateway: true,
      subnetConfiguration: [
        {
          cidrMask: 24,
          name: `public-subnet-for-${projectName}`,
          subnetType: ec2.SubnetType.PUBLIC
        }, 
        {
          cidrMask: 24,
          name: `private-subnet-for-${projectName}`,
          subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS
        }
      ]
    });  

    const bedrockEndpoint = vpc.addInterfaceEndpoint(`bedrock-endpoint-${projectName}`, {
      privateDnsEnabled: true,
      service: new ec2.InterfaceVpcEndpointService(`com.amazonaws.${region}.bedrock-runtime`, 443)
    });
    bedrockEndpoint.connections.allowDefaultPortFrom(ec2.Peer.ipv4(vpc.vpcCidrBlock), `allowBedrockPortFrom-${projectName}`)

    bedrockEndpoint.addToPolicy(
      new iam.PolicyStatement({
        principals: [new iam.AnyPrincipal()],
        actions: ['bedrock:*'],
        resources: ['*'],
      }),
    );

    // ALB SG
    const albSg = new ec2.SecurityGroup(this, `alb-sg-for-${projectName}`, {
      vpc: vpc,
      allowAllOutbound: true,
      securityGroupName: `alb-sg-for-${projectName}`,
      description: 'security group for alb'
    });
    
    // ALB
    const alb = new elbv2.ApplicationLoadBalancer(this, `alb-for-${projectName}`, {
      internetFacing: true,
      vpc: vpc,
      vpcSubnets: {
        subnets: vpc.publicSubnets
      },
      securityGroup: albSg,
      loadBalancerName: `alb-for-${projectName}`
    });
    alb.applyRemovalPolicy(cdk.RemovalPolicy.DESTROY); 

    new cdk.CfnOutput(this, `albUrl-for-${projectName}`, {
      value: `http://${alb.loadBalancerDnsName}/`,
      description: `albUrl-${projectName}`,
      exportName: `albUrl-${projectName}`
    });    

    // CloudFront
    const CUSTOM_HEADER_NAME = "X-Custom-Header"
    const CUSTOM_HEADER_VALUE = `${projectName}_12dab15e4s31` // Temporary value
    const albOrigin = new origins.LoadBalancerV2Origin(alb, {      
      httpPort: 80,
      customHeaders: {[CUSTOM_HEADER_NAME] : CUSTOM_HEADER_VALUE},
      originShieldEnabled: false,
      protocolPolicy: cloudFront.OriginProtocolPolicy.HTTP_ONLY      
    });
    const s3Origin = origins.S3BucketOrigin.withOriginAccessControl(s3Bucket);

    const distribution = new cloudFront.Distribution(this, `cloudfront-for-${projectName}`, {
      comment: `CloudFront-for-${projectName}`,
      defaultBehavior: {
        origin: albOrigin,
        viewerProtocolPolicy: cloudFront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        allowedMethods: cloudFront.AllowedMethods.ALLOW_ALL,
        cachePolicy: cloudFront.CachePolicy.CACHING_DISABLED,
        originRequestPolicy: cloudFront.OriginRequestPolicy.ALL_VIEWER        
      },
      additionalBehaviors: {
        '/docs/*': {
          origin: s3Origin,
          viewerProtocolPolicy: cloudFront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
          allowedMethods: cloudFront.AllowedMethods.ALLOW_ALL,
          cachePolicy: cloudFront.CachePolicy.CACHING_DISABLED,
          originRequestPolicy: cloudFront.OriginRequestPolicy.CORS_S3_ORIGIN
        },
        '/images/*': {
          origin: s3Origin,
          viewerProtocolPolicy: cloudFront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
          allowedMethods: cloudFront.AllowedMethods.ALLOW_ALL,
          cachePolicy: cloudFront.CachePolicy.CACHING_DISABLED,
          originRequestPolicy: cloudFront.OriginRequestPolicy.CORS_S3_ORIGIN
        },
        '/artifacts/*': {
          origin: s3Origin,
          viewerProtocolPolicy: cloudFront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
          allowedMethods: cloudFront.AllowedMethods.ALLOW_ALL,
          cachePolicy: cloudFront.CachePolicy.CACHING_DISABLED,
          originRequestPolicy: cloudFront.OriginRequestPolicy.CORS_S3_ORIGIN
        }
      },
      priceClass: cloudFront.PriceClass.PRICE_CLASS_200
    }); 

    // Update S3 bucket policy to allow access from CloudFront
    s3Bucket.addToResourcePolicy(new iam.PolicyStatement({
      effect: iam.Effect.ALLOW,
      actions: ['s3:GetObject'],
      resources: [
        s3Bucket.arnForObjects('*'),
        s3Bucket.arnForObjects('docs/*'),
        s3Bucket.arnForObjects('images/*'),
        s3Bucket.arnForObjects('artifacts/*')
      ],
      principals: [new iam.ServicePrincipal('cloudfront.amazonaws.com')],
      conditions: {
        StringEquals: {
          'AWS:SourceArn': `arn:aws:cloudfront::${accountId}:distribution/${distribution.distributionId}`
        }
      }
    }));

    new cdk.CfnOutput(this, `distributionDomainName-for-${projectName}`, {
      value: 'https://'+distribution.domainName,
      description: 'The domain name of the Distribution'
    });    

    // EC2 Security Group
    const ec2Sg = new ec2.SecurityGroup(this, `ec2-sg-for-${projectName}`,
      {
        vpc: vpc,
        allowAllOutbound: true,
        description: "Security group for ec2",
        securityGroupName: `ec2-sg-for-${projectName}`,
      }
    );

    const targetPort = 8501;  // 8080 8501
    ec2Sg.connections.allowFrom(albSg, ec2.Port.tcp(targetPort), 'allow traffic from alb') // alb -> ec2
    ec2Sg.connections.allowTo(bedrockEndpoint, ec2.Port.tcp(443), 'allow traffic to bedrock endpoint') // ec2 -> bedrock
    
    // lambda-rag
    const roleLambdaRag = new iam.Role(this, `role-lambda-rag-for-${projectName}`, {
      roleName: `role-lambda-rag-for-${projectName}-${region}`,
      assumedBy: new iam.CompositePrincipal(
        new iam.ServicePrincipal("lambda.amazonaws.com"),
        new iam.ServicePrincipal("bedrock.amazonaws.com"),
      ),
      // managedPolicies: [cdk.aws_iam.ManagedPolicy.fromAwsManagedPolicyName('CloudWatchLogsFullAccess')] 
    });
    // roleLambdaRag.addManagedPolicy({  // grant log permission
    //   managedPolicyArn: 'arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole',
    // });
    const CreateLogPolicy = new iam.PolicyStatement({  
      resources: [`arn:aws:logs:${region}:${accountId}:*`],
      actions: ['logs:CreateLogGroup'],
    });        
    roleLambdaRag.attachInlinePolicy( 
      new iam.Policy(this, `create-log-policy-lambda-rag-for-${projectName}`, {
        statements: [CreateLogPolicy],
      }),
    );
    const CreateLogStreamPolicy = new iam.PolicyStatement({  
      resources: [`arn:aws:logs:${region}:${accountId}:log-group:/aws/lambda/*`],
      actions: ["logs:CreateLogStream","logs:PutLogEvents"],
    });        
    roleLambdaRag.attachInlinePolicy( 
      new iam.Policy(this, `create-stream-log-policy-lambda-rag-for-${projectName}`, {
        statements: [CreateLogStreamPolicy],
      }),
    );      
    tavilyApiSecret.grantRead(roleLambdaRag) 

    // bedrock
    roleLambdaRag.attachInlinePolicy( 
      new iam.Policy(this, `tool-bedrock-invoke-policy-for-${projectName}`, {
        statements: [bedrockInvokePolicy],
      }),
    );  
    roleLambdaRag.attachInlinePolicy( 
      new iam.Policy(this, `tool-bedrock-agent-opensearch-policy-for-${projectName}`, {
        statements: [knowledgeBaseOpenSearchPolicy],
      }),
    );  
    roleLambdaRag.attachInlinePolicy( 
      new iam.Policy(this, `tool-bedrock-agent-bedrock-policy-for-${projectName}`, {
        statements: [knowledgeBaseBedrockPolicy],
      }),
    );  
    
    const lambdaKnowledgeBase = new lambda.DockerImageFunction(this, `knowledge-base-for-${projectName}`, {
      description: 'RAG based on Knoeledge Base',
      functionName: `knowledge-base-for-${projectName}`,
      code: lambda.DockerImageCode.fromImageAsset(path.join(__dirname, '../../lambda-knowledge-base')),
      timeout: cdk.Duration.seconds(120),
      memorySize: 4096,
      role: roleLambdaRag,
      environment: {
        bedrock_region: String(region),  
        projectName: projectName,
        "sharing_url": 'https://'+distribution.domainName,
      }
    });
    lambdaKnowledgeBase.grantInvoke(new cdk.aws_iam.ServicePrincipal("bedrock.amazonaws.com"));     
    
    const userData = ec2.UserData.forLinux();
    const environment = {
      "projectName": projectName,
      "accountId": accountId,
      "region": region,
      "knowledge_base_role": knowledge_base_role.roleArn,
      "collectionArn": collectionArn,
      "opensearch_url": OpenSearchCollection.attrCollectionEndpoint,
      "s3_bucket": s3Bucket.bucketName,      
      "s3_arn": s3Bucket.bucketArn,
      "sharing_url": 'https://'+distribution.domainName,
    }    
    new cdk.CfnOutput(this, `environment-for-${projectName}`, {
      value: JSON.stringify(environment),
      description: `environment-${projectName}`,
      exportName: `environment-${projectName}`
    });
    
    const gitName = 'mcp'
    const commands = [
      'yum install git python-pip docker -y',
      'pip install pip --upgrade',
      'systemctl start docker',
      'systemctl enable docker',
      'usermod -aG docker ec2-user',
      `runuser -l ec2-user -c 'cd && git clone https://github.com/kyopark2014/${gitName}'`,
      `json='${JSON.stringify(environment)}' && echo "$json">/home/ec2-user/${gitName}/application/config.json`,
      `runuser -l ec2-user -c 'cd ${gitName} && docker build -t streamlit-app .'`,
      `yum install -y amazon-cloudwatch-agent`,
      `mkdir -p /opt/aws/amazon-cloudwatch-agent/etc/`, 
      `cp /home/ec2-user/${gitName}/amazon-cloudwatch-agent.json /opt/aws/amazon-cloudwatch-agent/etc/`,
      `chmod 644 /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json`,
      `systemctl enable amazon-cloudwatch-agent`,
      `systemctl start amazon-cloudwatch-agent`,
      `mkdir -p /etc/docker`,
      `cp /home/ec2-user/${gitName}/daemon.json /etc/docker/`,
      `systemctl restart docker`,
      `runuser -l ec2-user -c 'docker run -d -p 8501:8501 streamlit-app'`
    ];
    userData.addCommands(...commands);
    
    // EC2 instance
    const appInstance = new ec2.Instance(this, `app-for-${projectName}`, {
      instanceName: `app-for-${projectName}`,
      instanceType: new ec2.InstanceType('m5.large'), // t2.small
      // instanceType: ec2.InstanceType.of(ec2.InstanceClass.T2, ec2.InstanceSize.SMALL),
      machineImage: new ec2.AmazonLinuxImage({
        generation: ec2.AmazonLinuxGeneration.AMAZON_LINUX_2023
      }),
      // machineImage: ec2.MachineImage.latestAmazonLinux2023(),
      vpc: vpc,
      vpcSubnets: {
        subnets: vpc.privateSubnets  
      },
      securityGroup: ec2Sg,
      role: ec2Role,
      userData: userData,
      blockDevices: [{
        deviceName: '/dev/xvda',
        volume: ec2.BlockDeviceVolume.ebs(80, {
          deleteOnTermination: true,
          encrypted: true,
        }),
      }],
      detailedMonitoring: true,
      instanceInitiatedShutdownBehavior: ec2.InstanceInitiatedShutdownBehavior.TERMINATE,
    }); 
    s3Bucket.grantReadWrite(appInstance);
    appInstance.applyRemovalPolicy(cdk.RemovalPolicy.DESTROY);

    // ALB Target
    const targets: elbv2_tg.InstanceTarget[] = new Array();
    targets.push(new elbv2_tg.InstanceTarget(appInstance)); 
    
    // ALB Listener
    const listener = alb.addListener(`HttpListener-for-${projectName}`, {   
      port: 80,
      open: true
    });     
    const targetGroup = listener.addTargets(`WebEc2Target-for-${projectName}`, {
      targetGroupName: `TG-for-${projectName}`,
      targets: targets,
      protocol: elbv2.ApplicationProtocol.HTTP,
      port: targetPort,
      conditions: [elbv2.ListenerCondition.httpHeader(CUSTOM_HEADER_NAME, [CUSTOM_HEADER_VALUE])],
      priority: 10      
    });
    listener.addTargetGroups(`addTG-for-${projectName}`, {
      targetGroups: [targetGroup]
    })
    const defaultAction = elbv2.ListenerAction.fixedResponse(403, {
        contentType: "text/plain",
        messageBody: 'Access denied',
    })
    listener.addAction(`RedirectHttpListener-for-${projectName}`, {
      action: defaultAction
    });  
  }
}

param(
    [Parameter(Mandatory=$true)][string]$TaskDefinition,
    [ValidateSet('ai-engineer')][string]$Application = 'ai-engineer',
    [ValidateSet('us-east-1')][string]$Region = 'us-east-1',
    [string]$Python = '.venv/Scripts/python.exe',
    [switch]$CreateService,
    [string]$SecurityGroupId,
    [switch]$Apply
)
$ErrorActionPreference = 'Stop'
& $Python "$PSScriptRoot/plan.py" --validate $TaskDefinition
if ($LASTEXITCODE -ne 0) { throw 'Exact worker task validation failed' }
$task = Get-Content -Raw -LiteralPath $TaskDefinition | ConvertFrom-Json
if ($task.family -ne 'mc-worker-ai-engineer' -or $task.cpu -ne '512' -or $task.memory -ne '2048') {
    throw 'Task differs from the exact reviewed service size'
}
if ($CreateService -and $SecurityGroupId -notmatch '^sg-[a-f0-9]{17}$') {
    throw 'First-service creation requires the reviewed egress-only security group'
}
if (-not $Apply) { Write-Output 'Plan only: review task, prerequisites, spend, and cleanup before -Apply.'; return }
$identity = aws sts get-caller-identity --region $Region --output json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $identity.Account -ne '298199649527') { throw 'AWS account mismatch' }
$service = aws ecs describe-services --cluster mission-control --services mc-worker-ai-engineer --region $Region --output json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect exact service; no registration attempted' }
$expectedSubnets = @('subnet-070333667ef52535d','subnet-0efe52bd60be362ea','subnet-0eb0cdfbe77ed7327','subnet-088e18d96815df31d','subnet-0a6434aad9d46d724','subnet-018b0b7eb2bab137c')
if ($CreateService) {
    if ($service.services.Count -ne 0 -or $service.failures.Count -ne 1 -or $service.failures[0].reason -ne 'MISSING') {
        throw 'First-service creation requires an absent service in the existing reviewed cluster'
    }
} else {
    if ($service.services.Count -ne 1 -or $service.services[0].status -ne 'ACTIVE') { throw 'Select -CreateService only for reviewed first-service provisioning' }
    $existing = $service.services[0]
    if ($existing.desiredCount -gt 1 -or $existing.runningCount -gt 1 -or $existing.pendingCount -gt 0 -or $existing.deployments.Count -ne 1 -or $existing.deployments[0].rolloutState -ne 'COMPLETED') { throw 'Existing worker deployment must be stable and contain at most one task' }
    if ($existing.launchType -ne 'FARGATE' -or $existing.schedulingStrategy -ne 'REPLICA' -or $existing.deploymentController.type -ne 'ECS' -or $existing.loadBalancers.Count -ne 0 -or $existing.enableExecuteCommand -or $existing.serviceConnectConfiguration.enabled) { throw 'Existing service differs from reviewed worker topology' }
    $network = $existing.networkConfiguration.awsvpcConfiguration
    if ($network.assignPublicIp -ne 'ENABLED' -or $network.securityGroups.Count -ne 1 -or $network.subnets.Count -ne 6 -or @(Compare-Object $expectedSubnets $network.subnets).Count -ne 0) { throw 'Existing service network differs from the reviewed contract' }
    if ($SecurityGroupId -and $SecurityGroupId -ne $network.securityGroups[0]) { throw 'Requested security group differs from existing service' }
    $SecurityGroupId = $network.securityGroups[0]
}
$group = aws ec2 describe-security-groups --group-ids $SecurityGroupId --region $Region --output json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $group.SecurityGroups.Count -ne 1) { throw 'Security group unavailable' }
$selectedGroup = $group.SecurityGroups[0]
if ($selectedGroup.VpcId -ne 'vpc-04db3b23ff1cee487' -or $selectedGroup.GroupName -ne 'mc-worker-egress-only' -or $selectedGroup.IpPermissions.Count -ne 0) { throw 'Security group differs from the reviewed VPC/name/zero-inbound policy' }
$subnets = aws ec2 describe-subnets --filters Name=vpc-id,Values=vpc-04db3b23ff1cee487 --region $Region --output json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Cannot verify selected network' }
foreach ($subnetId in $expectedSubnets) {
    $selectedSubnet = @($subnets.Subnets | Where-Object { $_.SubnetId -eq $subnetId -and $_.State -eq 'available' -and $_.DefaultForAz -and $_.MapPublicIpOnLaunch })
    if ($selectedSubnet.Count -ne 1) { throw "Selected public subnet is unavailable: $subnetId" }
}
$arn = aws ecs register-task-definition --cli-input-json "file://$TaskDefinition" --region $Region --query taskDefinition.taskDefinitionArn --output text
if ($LASTEXITCODE -ne 0) { throw 'Task registration failed' }
if ($CreateService) {
    $servicePlan = [IO.Path]::GetTempFileName()
    try {
        & $Python "$PSScriptRoot/service.py" --task-definition $arn --security-group $SecurityGroupId --out $servicePlan
        if ($LASTEXITCODE -ne 0) { throw 'First-service contract validation failed; retain registered revision' }
        aws ecs create-service --cli-input-json "file://$servicePlan" --region $Region --query service.serviceArn --output text
        if ($LASTEXITCODE -ne 0) { throw 'Create outcome uncertain; inspect exact service before any retry' }
    } finally {
        Remove-Item -LiteralPath $servicePlan -Force
    }
} else {
    # STOPPING tasks can still execute shutdown work. Retain their exact identities
    # and await terminal task state before starting the new base worker.
    $oldTaskArns = @()
    foreach ($desiredStatus in @('RUNNING','STOPPED')) {
        $listed = aws ecs list-tasks --cluster mission-control --service-name mc-worker-ai-engineer --desired-status $desiredStatus --region $Region --output json | ConvertFrom-Json
        if ($LASTEXITCODE -ne 0) { throw 'Cannot inventory old worker tasks; no replacement start attempted' }
        $oldTaskArns += @($listed.taskArns)
    }
    $oldTaskArns = @($oldTaskArns | Sort-Object -Unique)
    aws ecs update-service --cluster mission-control --service mc-worker-ai-engineer --desired-count 0 --region $Region --query service.serviceArn --output text
    if ($LASTEXITCODE -ne 0) { throw 'Worker drain outcome uncertain; inspect before resuming' }
    aws ecs wait services-stable --cluster mission-control --services mc-worker-ai-engineer --region $Region
    if ($LASTEXITCODE -ne 0) { throw 'Worker drain did not stabilize; new revision remains unstarted' }
    # Include any replacement that started between the first inventory and drain.
    foreach ($desiredStatus in @('RUNNING','STOPPED')) {
        $listed = aws ecs list-tasks --cluster mission-control --service-name mc-worker-ai-engineer --desired-status $desiredStatus --region $Region --output json | ConvertFrom-Json
        if ($LASTEXITCODE -ne 0) { throw 'Cannot reconcile drained worker identities; no replacement start attempted' }
        $oldTaskArns += @($listed.taskArns)
    }
    $oldTaskArns = @($oldTaskArns | Sort-Object -Unique)
    foreach ($oldTaskArn in $oldTaskArns) {
        aws ecs wait tasks-stopped --cluster mission-control --tasks $oldTaskArn --region $Region
        if ($LASTEXITCODE -ne 0) { throw 'Old worker has not stopped; new revision remains unstarted' }
    }
    aws ecs update-service --cluster mission-control --service mc-worker-ai-engineer --task-definition $arn --desired-count 1 --availability-zone-rebalancing DISABLED --deployment-configuration 'minimumHealthyPercent=0,maximumPercent=100,deploymentCircuitBreaker={enable=true,rollback=true}' --region $Region --query service.serviceArn --output text
    if ($LASTEXITCODE -ne 0) { throw 'Service update failed; retain registered revision for reconciliation' }
}
aws ecs wait services-stable --cluster mission-control --services mc-worker-ai-engineer --region $Region
if ($LASTEXITCODE -ne 0) { throw 'Service did not stabilize; inspect exact task logs before retrying' }
Write-Output 'Service stable; readiness, build, laptop-off, restart and cost evidence still required.'

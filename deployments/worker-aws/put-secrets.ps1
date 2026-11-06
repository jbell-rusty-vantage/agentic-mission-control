param(
    [ValidateSet('ai-engineer')][string]$Application = 'ai-engineer',
    [ValidateSet('us-east-1')][string]$Region = 'us-east-1',
    [Parameter(Mandatory=$true)][string[]]$Names,
    [switch]$OwnerExecution
)
$ErrorActionPreference = 'Stop'
if (-not $OwnerExecution) { throw 'Owner-run secret write requires -OwnerExecution; no values are read.' }
$allowed = @('MC_AI_ENGINEER_RUNTIME_DSN','MC_AI_ENGINEER_FAMILY_DSN','LANGGRAPH_CHECKPOINT_DATABASE_DIRECT','TEMPORAL_CLOUD_API_KEY','ANTHROPIC_API_KEY','OPENAI_API_KEY','CURSOR_API_KEY')
if (@($Names | Where-Object { $_ -notin $allowed }).Count) { throw 'Unapproved secret name' }
$identity = aws sts get-caller-identity --region $Region --output json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0 -or $identity.Account -ne '298199649527') { throw 'AWS account mismatch' }
foreach ($name in $Names) {
    $value = [Environment]::GetEnvironmentVariable($name)
    if ([string]::IsNullOrWhiteSpace($value)) { throw "Required environment input absent: $name" }
    $temporary = [IO.Path]::GetTempFileName()
    try {
        [IO.File]::WriteAllText($temporary, $value, [Text.UTF8Encoding]::new($false))
        # Secret resources are provisioned separately; this script only writes values.
        aws secretsmanager put-secret-value --secret-id "mission-control/ai-engineer/$name" --secret-string "file://$temporary" --region $Region --query ARN --output text
        if ($LASTEXITCODE -ne 0) { throw "Secret write failed: $name" }
    } finally {
        $value = $null
        Remove-Item -LiteralPath $temporary -Force
    }
}

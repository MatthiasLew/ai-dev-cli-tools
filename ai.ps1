param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

python -m ai_dev_tools.cli @Args
exit $LASTEXITCODE

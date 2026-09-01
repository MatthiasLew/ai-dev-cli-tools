param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

python scripts/dev.py @Args
exit $LASTEXITCODE

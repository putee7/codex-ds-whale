$ErrorActionPreference = 'Stop'
function Get-Sha256([string]$Path) {
    $stream = [IO.File]::OpenRead($Path)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-','').ToLowerInvariant() }
    finally { $algorithm.Dispose(); $stream.Dispose() }
}
$action = $args[0]
if ($action -notin @('install','start','stop','doctor','uninstall')) { throw 'Unknown command.' }
$forward = @()
if ($args.Count -gt 1) { $forward = $args[1..($args.Count-1)] }
$packageRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$prefix = $packageRoot + [IO.Path]::DirectorySeparatorChar
$runtime = Join-Path $packageRoot 'runtime'
$pin = Get-Content -LiteralPath (Join-Path $packageRoot 'runtime.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if (!(Test-Path -LiteralPath (Join-Path $runtime 'python.exe'))) {
    if (Test-Path -LiteralPath $runtime) { throw 'An incomplete runtime directory exists. Rename it and retry; it was not deleted.' }
    Write-Host ('Downloading project-local CPython ' + $pin.version + ' from python.org. The release ZIP already includes it.')
    $staging = Join-Path $packageRoot ('.runtime-staging-' + [Guid]::NewGuid().ToString('N'))
    $resolvedStaging = [IO.Path]::GetFullPath($staging)
    $resolvedRuntime = [IO.Path]::GetFullPath($runtime)
    if (!$resolvedStaging.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase) -or !$resolvedRuntime.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)) { throw 'Runtime target leaves the package directory.' }
    New-Item -ItemType Directory -Path $staging | Out-Null
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $archive = Join-Path $staging 'runtime.zip'
        $uri = [Uri]$pin.url
        if ($uri.Scheme -ne 'https' -or $uri.Host -ne 'www.python.org') { throw 'Runtime must come from official python.org HTTPS.' }
        $request = [Net.HttpWebRequest]::Create($uri)
        $request.Timeout = 60000
        $request.ReadWriteTimeout = 60000
        $response = $request.GetResponse()
        $inputStream = $response.GetResponseStream()
        $outputStream = [IO.File]::Create($archive)
        try { $inputStream.CopyTo($outputStream) }
        finally { $outputStream.Dispose(); $inputStream.Dispose(); $response.Dispose() }
        if ((Get-Sha256 $archive) -ne $pin.sha256) { throw 'Official runtime SHA256 mismatch.' }
        $extracted = Join-Path $staging 'files'
        Add-Type -AssemblyName System.IO.Compression.FileSystem
        [IO.Compression.ZipFile]::ExtractToDirectory($archive,$extracted)
        Move-Item -LiteralPath $extracted -Destination $runtime
    } finally {
        if (Test-Path -LiteralPath $resolvedStaging) { Remove-Item -LiteralPath $resolvedStaging -Recurse -Force }
    }
}
$runtimePrefix = [IO.Path]::GetFullPath($runtime) + [IO.Path]::DirectorySeparatorChar
$checks = Get-Content -LiteralPath (Join-Path $packageRoot 'runtime-files.json') -Raw -Encoding UTF8 | ConvertFrom-Json
foreach ($entry in $checks.files.PSObject.Properties) {
    $target = [IO.Path]::GetFullPath((Join-Path $runtime $entry.Name))
    if (!$target.StartsWith($runtimePrefix,[StringComparison]::OrdinalIgnoreCase)) { throw 'Unsafe runtime file path.' }
    if (!(Test-Path -LiteralPath $target) -or (Get-Sha256 $target) -ne $entry.Value) { throw ('Runtime integrity check failed: ' + $entry.Name) }
}
& (Join-Path $runtime 'python.exe') (Join-Path $packageRoot 'app/run.py') $action @forward
exit $LASTEXITCODE

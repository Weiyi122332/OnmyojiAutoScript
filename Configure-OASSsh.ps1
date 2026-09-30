[CmdletBinding()]
param(
    [string]$PrivateKeyPath = (Join-Path $env:USERPROFILE '.ssh\oas_updater'),
    [string]$ConfigPath = (Join-Path $env:USERPROFILE '.ssh\config'),
    [string]$RepositoryPath = '',
    [switch]$UsePort22,
    [switch]$NoClipboard
)

$ErrorActionPreference = 'Stop'

$PrivateKeyPath = [System.IO.Path]::GetFullPath($PrivateKeyPath)
$ConfigPath = [System.IO.Path]::GetFullPath($ConfigPath)
if ($PrivateKeyPath -match '[\r\n"]' -or $ConfigPath -match '[\r\n]') {
    throw '密钥和配置文件路径不能包含换行或双引号。'
}

$Ssh = (Get-Command ssh -CommandType Application -ErrorAction Stop).Source
$SshKeygen = (Get-Command ssh-keygen -CommandType Application -ErrorAction Stop).Source
$ConfigDirectory = Split-Path -Parent $ConfigPath
New-Item -ItemType Directory -Path $ConfigDirectory -Force | Out-Null

Write-Host '正在检查 OAS 专用 SSH 密钥……'
$KeyDirectory = Split-Path -Parent $PrivateKeyPath
New-Item -ItemType Directory -Path $KeyDirectory -Force | Out-Null
$PublicKeyPath = "$PrivateKeyPath.pub"

if (Test-Path -LiteralPath $PrivateKeyPath -PathType Leaf) {
    if (-not (Test-Path -LiteralPath $PublicKeyPath -PathType Leaf)) {
        Write-Host '已有私钥，正在恢复对应公钥……'
        $RecoveredKey = & $SshKeygen -y -f $PrivateKeyPath
        if ($LASTEXITCODE -ne 0 -or -not $RecoveredKey) {
            throw '无法从现有私钥恢复公钥，未修改 SSH 配置。'
        }
        [System.IO.File]::WriteAllText($PublicKeyPath, ($RecoveredKey.Trim() + "`n"), (New-Object System.Text.UTF8Encoding($false)))
    } else {
        Write-Host '已找到密钥，继续使用现有文件。'
    }
} elseif (Test-Path -LiteralPath $PublicKeyPath) {
    throw "发现公钥但缺少私钥：$PublicKeyPath。为避免覆盖现有文件，已停止。"
} else {
    Write-Host '未找到密钥，正在生成用于自动更新的专用密钥……'
    # 空口令使无人值守的自动更新可以使用这把密钥。
    & $SshKeygen -q -t ed25519 -N '""' -f $PrivateKeyPath -C 'oas-updater'
    if ($LASTEXITCODE -ne 0) {
        throw '生成 SSH 密钥失败，未修改 SSH 配置。'
    }
}

$PublicKey = [System.IO.File]::ReadAllText($PublicKeyPath).Trim()
if ($PublicKey -notmatch '^ssh-ed25519\s+\S+') {
    throw "公钥格式不正确：$PublicKeyPath。未修改 SSH 配置。"
}

$Begin = '# BEGIN OAS updater SSH alias'
$End = '# END OAS updater SSH alias'
$HostName = if ($UsePort22) { 'github.com' } else { 'ssh.github.com' }
$Port = if ($UsePort22) { 22 } else { 443 }
$KeyForSsh = $PrivateKeyPath.Replace('\', '/')
$Block = @(
    $Begin
    'Host github-oas'
    "    HostName $HostName"
    "    Port $Port"
    '    User git'
    "    IdentityFile `"$KeyForSsh`""
    '    IdentitiesOnly yes'
    $End
) -join "`r`n"
$Block += "`r`n"

$Existing = if (Test-Path -LiteralPath $ConfigPath) {
    [System.IO.File]::ReadAllText($ConfigPath)
} else {
    ''
}

$Start = $Existing.IndexOf($Begin, [System.StringComparison]::Ordinal)
$Finish = $Existing.IndexOf($End, [System.StringComparison]::Ordinal)
if (($Start -ge 0) -ne ($Finish -ge 0)) {
    throw "SSH 配置中的 OAS 专用区块不完整：$ConfigPath。未修改配置。"
}

if ($Start -ge 0) {
    if ($Finish -le $Start) {
        throw "SSH 配置中的 OAS 专用区块顺序错误：$ConfigPath。未修改配置。"
    }
    $SuffixStart = $Finish + $End.Length
    if ($Existing.Substring($SuffixStart).StartsWith("`r`n")) {
        $SuffixStart += 2
    } elseif ($Existing.Substring($SuffixStart).StartsWith("`n")) {
        $SuffixStart += 1
    }
    $OutsideBlock = $Existing.Substring(0, $Start) + $Existing.Substring($SuffixStart)
} else {
    $OutsideBlock = $Existing
}

foreach ($Match in [regex]::Matches($OutsideBlock, '(?im)^\s*Host\s+([^\r\n#]+)')) {
    $Names = $Match.Groups[1].Value.Trim() -split '\s+'
    if ($Names -contains 'github-oas') {
        throw "SSH 配置中已有非本脚本管理的 github-oas 别名：$ConfigPath。未修改配置。"
    }
}

if ($Start -ge 0) {
    $Updated = $Existing.Substring(0, $Start) + $Block + $Existing.Substring($SuffixStart)
} else {
    $Separator = if ($Existing.Length -eq 0 -or $Existing.EndsWith("`n")) { '' } else { "`r`n" }
    $Updated = $Existing + $Separator + $Block
}

$TemporaryConfig = Join-Path $ConfigDirectory ([System.IO.Path]::GetRandomFileName())
try {
    Write-Host '正在配置 github-oas SSH 别名……'
    [System.IO.File]::WriteAllText($TemporaryConfig, $Updated, (New-Object System.Text.UTF8Encoding($false)))
    $Resolved = & $Ssh -G -F $TemporaryConfig github-oas 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "SSH 配置检查失败：$Resolved"
    }
    if ($Updated -ne $Existing) {
        [System.IO.File]::WriteAllText($ConfigPath, $Updated, (New-Object System.Text.UTF8Encoding($false)))
    }
} finally {
    if (Test-Path -LiteralPath $TemporaryConfig) {
        [System.IO.File]::Delete($TemporaryConfig)
    }
}

Write-Host "已配置 github-oas → $HostName`:$Port"
Write-Host "私钥保存在本机：$PrivateKeyPath"
Write-Host "SSH 配置文件：$ConfigPath"
Write-Host ''
Write-Host '请把下面这一整行公钥发给仓库所有者，私钥文件不要发送：'
Write-Output $PublicKey

if (-not $NoClipboard -and (Get-Command Set-Clipboard -ErrorAction SilentlyContinue)) {
    try {
        Set-Clipboard -Value $PublicKey
        Write-Host '公钥已复制到剪贴板。'
    } catch {
        Write-Host '无法使用剪贴板，请手动复制上面的公钥。'
    }
}

Write-Host '仓库所有者添加只读部署密钥后，运行以下命令验证连接：'
Write-Host 'git ls-remote git@github-oas:Weiyi122332/OnmyojiAutoScript.git refs/heads/wy'

$Git = Get-Command git -CommandType Application -ErrorAction Stop | Select-Object -First 1
if ([string]::IsNullOrWhiteSpace($RepositoryPath)) {
    $RepositoryPath = $PSScriptRoot
}
if ([string]::IsNullOrWhiteSpace($RepositoryPath)) {
    $RepositoryPath = (Get-Location).Path
}
$RepositoryPath = [System.IO.Path]::GetFullPath($RepositoryPath.Trim())
$RepositoryRoot = & $Git.Source -C $RepositoryPath rev-parse --show-toplevel 2>$null
if ($LASTEXITCODE -ne 0 -or -not $RepositoryRoot) {
    $RepositoryPath = Read-Host '请输入 OAS 项目本地目录（例如 D:\OnmyojiAutoScript）'
    if ([string]::IsNullOrWhiteSpace($RepositoryPath)) {
        throw '未提供项目目录，SSH 已配置，但未修改 Git 仓库地址。'
    }
    $RepositoryPath = [System.IO.Path]::GetFullPath($RepositoryPath.Trim())
    $RepositoryRoot = & $Git.Source -C $RepositoryPath rev-parse --show-toplevel 2>$null
    if ($LASTEXITCODE -ne 0 -or -not $RepositoryRoot) {
        throw "指定目录不是 Git 仓库：$RepositoryPath。未修改仓库地址。"
    }
}

$OriginUrl = & $Git.Source -C $RepositoryRoot remote get-url origin 2>$null
if ($LASTEXITCODE -ne 0 -or -not $OriginUrl) {
    throw "在项目中找不到 origin 远程地址：$RepositoryRoot。SSH 已配置，但未修改仓库地址。"
}
$ExpectedOriginPattern = '(?i)^(https://github\.com/Weiyi122332/OnmyojiAutoScript(?:\.git)?/?|git@github\.com:Weiyi122332/OnmyojiAutoScript(?:\.git)?|ssh://git@github\.com/Weiyi122332/OnmyojiAutoScript(?:\.git)?|git@github-oas:Weiyi122332/OnmyojiAutoScript(?:\.git)?)$'
if ($OriginUrl.Trim() -notmatch $ExpectedOriginPattern) {
    throw "当前 origin 指向其他地址：$($OriginUrl.Trim())。为避免改错仓库，未修改地址。"
}

$NewOriginUrl = 'git@github-oas:Weiyi122332/OnmyojiAutoScript.git'
if ($OriginUrl.Trim() -ne $NewOriginUrl) {
    & $Git.Source -C $RepositoryRoot remote set-url origin $NewOriginUrl
    if ($LASTEXITCODE -ne 0) {
        throw "修改 origin 地址失败：$RepositoryRoot"
    }
}
Write-Host "已将项目 origin 配置为：$NewOriginUrl"
Write-Host "项目目录：$RepositoryRoot"

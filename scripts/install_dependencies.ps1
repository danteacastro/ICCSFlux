#Requires -RunAsAdministrator
<#
.SYNOPSIS
    NISystem Dependency Installation Script for Windows
.DESCRIPTION
    Installs all required dependencies for the NISystem stack on Windows 10/11
#>

$ErrorActionPreference = "Stop"

Write-Host "==============================================" -ForegroundColor Cyan
Write-Host "NISystem Dependency Installation (Windows)"
Write-Host "==============================================" -ForegroundColor Cyan
Write-Host ""

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectDir = Split-Path -Parent $ScriptDir

# Check if running as Administrator
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Warning: Some installations may require administrator privileges" -ForegroundColor Yellow
}

function Install-Chocolatey {
    Write-Host ""
    Write-Host "----------------------------------------" -ForegroundColor Yellow
    Write-Host "Checking Chocolatey package manager..."
    Write-Host "----------------------------------------" -ForegroundColor Yellow

    if (Get-Command choco -ErrorAction SilentlyContinue) {
        Write-Host "Chocolatey already installed" -ForegroundColor Green
    } else {
        Write-Host "Installing Chocolatey..." -ForegroundColor Yellow
        Set-ExecutionPolicy Bypass -Scope Process -Force
        [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
        Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
        Write-Host "Chocolatey installed" -ForegroundColor Green
    }
}

function Install-Python {
    Write-Host ""
    Write-Host "----------------------------------------" -ForegroundColor Yellow
    Write-Host "Installing Python..."
    Write-Host "----------------------------------------" -ForegroundColor Yellow

    if (Get-Command python -ErrorAction SilentlyContinue) {
        $version = python --version 2>&1
        Write-Host "Python already installed: $version" -ForegroundColor Green
    } else {
        choco install python --version=3.11.0 -y
        refreshenv
        Write-Host "Python installed" -ForegroundColor Green
    }

    # Create virtual environment
    Write-Host "Creating Python virtual environment..."
    $venvPath = Join-Path $ProjectDir "venv"

    if (-not (Test-Path $venvPath)) {
        python -m venv $venvPath
    }

    # Activate and install requirements
    $activateScript = Join-Path $venvPath "Scripts\Activate.ps1"
    & $activateScript

    python -m pip install --upgrade pip
    $requirementsPath = Join-Path $ProjectDir "services\daq_service\requirements.txt"
    pip install -r $requirementsPath

    Write-Host "Python dependencies installed" -ForegroundColor Green
}

function Install-NodeJS {
    Write-Host ""
    Write-Host "----------------------------------------" -ForegroundColor Yellow
    Write-Host "Installing Node.js..."
    Write-Host "----------------------------------------" -ForegroundColor Yellow

    if (Get-Command node -ErrorAction SilentlyContinue) {
        $version = node --version
        Write-Host "Node.js already installed: $version" -ForegroundColor Green
    } else {
        choco install nodejs-lts -y
        refreshenv
        Write-Host "Node.js installed" -ForegroundColor Green
    }
}

function Install-Mosquitto {
    Write-Host ""
    Write-Host "----------------------------------------" -ForegroundColor Yellow
    Write-Host "Installing Mosquitto MQTT Broker..."
    Write-Host "----------------------------------------" -ForegroundColor Yellow

    if (Get-Command mosquitto -ErrorAction SilentlyContinue) {
        Write-Host "Mosquitto already installed" -ForegroundColor Green
    } else {
        choco install mosquitto -y
        Write-Host "Mosquitto installed" -ForegroundColor Green
    }

    # Configure Mosquitto for local access
    $mosquittoConf = "C:\Program Files\mosquitto\mosquitto.conf"
    $nisystemConf = @"
# NISystem MQTT Configuration
listener 1883
allow_anonymous true
persistence true

# WebSocket support for browser clients
listener 9001
protocol websockets
"@

    # Check if config already has our settings
    if (Test-Path $mosquittoConf) {
        $content = Get-Content $mosquittoConf -Raw
        if ($content -notmatch "NISystem MQTT Configuration") {
            Add-Content $mosquittoConf "`n$nisystemConf"
            Write-Host "Mosquitto configured for NISystem" -ForegroundColor Green
        }
    }

    # Start Mosquitto service
    try {
        Start-Service mosquitto -ErrorAction SilentlyContinue
        Set-Service mosquitto -StartupType Automatic
        Write-Host "Mosquitto service started" -ForegroundColor Green
    } catch {
        Write-Host "Note: Start Mosquitto manually if needed" -ForegroundColor Yellow
    }
}

function Install-DashboardDependencies {
    Write-Host ""
    Write-Host "----------------------------------------" -ForegroundColor Yellow
    Write-Host "Installing Dashboard dependencies..."
    Write-Host "----------------------------------------" -ForegroundColor Yellow

    $dashboardPath = Join-Path $ProjectDir "dashboard"
    Push-Location $dashboardPath

    npm install

    Pop-Location
    Write-Host "Dashboard dependencies installed" -ForegroundColor Green
}

function Create-Directories {
    Write-Host ""
    Write-Host "----------------------------------------" -ForegroundColor Yellow
    Write-Host "Creating directories..."
    Write-Host "----------------------------------------" -ForegroundColor Yellow

    $dirs = @(
        (Join-Path $ProjectDir "logs"),
        (Join-Path $ProjectDir "data")
    )

    foreach ($dir in $dirs) {
        if (-not (Test-Path $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
            Write-Host "Created: $dir" -ForegroundColor Green
        }
    }
}

# Main installation sequence
try {
    Install-Chocolatey
    Install-Python
    Install-NodeJS
    Install-Mosquitto
    Install-DashboardDependencies
    Create-Directories

    Write-Host ""
    Write-Host "==============================================" -ForegroundColor Green
    Write-Host "Installation Complete!" -ForegroundColor Green
    Write-Host "==============================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "To start the system:"
    Write-Host "  1. Start MQTT:     net start mosquitto"
    Write-Host "  2. Start DAQ:      .\scripts\start_all.ps1"
    Write-Host "  3. Start Dashboard: cd dashboard && npm run dev"
    Write-Host ""
    Write-Host "Dashboard will be available at: http://localhost:5173"
    Write-Host ""
} catch {
    Write-Host "Installation failed: $_" -ForegroundColor Red
    exit 1
}

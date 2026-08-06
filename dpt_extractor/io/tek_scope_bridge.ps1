param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('discover', 'acquire', 'sync')]
    [string]$Operation,
    [string]$Resource = '',
    [string]$OutputPath = '',
    [string]$StatePath = ''
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)

$IviPath = 'C:\Program Files\IVI Foundation\VISA\Microsoft.NET\Framework64\v4.0.30319\VISA.NET Shared Components 8.0.2\Ivi.Visa.dll'
$NiVisaPath = 'C:\Program Files\IVI Foundation\VISA\Microsoft.NET\Framework64\v4.0.30319\NI VISA.NET 26.0\NationalInstruments.Visa.dll'

function Write-Result([object]$Value) {
    $json = $Value | ConvertTo-Json -Depth 8 -Compress
    [Console]::Out.WriteLine("RESULT`t$json")
}

function Write-ProgressLine([int]$Done, [int]$Total, [string]$Label) {
    [Console]::Out.WriteLine("PROGRESS`t$Done`t$Total`t$Label")
}

function Open-VisaManager {
    if (-not (Test-Path -LiteralPath $IviPath) -or -not (Test-Path -LiteralPath $NiVisaPath)) {
        throw 'NI-VISA .NET runtime was not found'
    }
    Add-Type -Path $IviPath
    Add-Type -Path $NiVisaPath
    return New-Object NationalInstruments.Visa.ResourceManager
}

function Open-Scope([object]$Manager, [string]$ResourceName) {
    $session = [Ivi.Visa.IMessageBasedSession]$Manager.Open($ResourceName)
    $session.TimeoutMilliseconds = 15000
    # Clear unread bytes left by an interrupted binary transfer before the
    # first text query on a newly opened USBTMC session.
    $session.Clear()
    return $session
}

function Write-Command([object]$Session, [string]$Command) {
    $Session.RawIO.Write("$Command`n")
}

function Invoke-Query([object]$Session, [string]$Command) {
    Write-Command $Session $Command
    return $Session.RawIO.ReadString().Trim().Trim('"')
}

function Read-IeeeBinaryBlock(
    [object]$Session,
    [long]$ExpectedPayloadBytes
) {
    # Read the definite-length IEEE block according to its header. Asking VISA
    # for payload + an arbitrary safety margin can make NI-VISA wait for bytes
    # that the scope will never send and eventually raise IOTimeoutException.
    try {
        [byte[]]$prefix = $Session.RawIO.Read([long]2)
    }
    catch {
        throw "Timed out waiting for the IEEE waveform block header: $($_.Exception.Message)"
    }
    if ($prefix.Length -ne 2 -or $prefix[0] -ne [byte][char]'#') {
        throw 'Oscilloscope returned an invalid IEEE waveform block header'
    }
    $digitCount = [int]$prefix[1] - [int][char]'0'
    if ($digitCount -le 0 -or $digitCount -gt 9) {
        throw 'Oscilloscope returned an unsupported IEEE waveform block length'
    }
    try {
        [byte[]]$lengthBytes = $Session.RawIO.Read([long]$digitCount)
    }
    catch {
        throw "Timed out reading the IEEE waveform block length: $($_.Exception.Message)"
    }
    if ($lengthBytes.Length -ne $digitCount) {
        throw 'Oscilloscope returned an incomplete IEEE waveform block length'
    }
    $lengthText = [Text.Encoding]::ASCII.GetString($lengthBytes)
    $payloadBytes = [long]::Parse(
        $lengthText,
        [Globalization.NumberStyles]::None,
        [Globalization.CultureInfo]::InvariantCulture
    )
    if ($payloadBytes -ne $ExpectedPayloadBytes) {
        throw "Oscilloscope waveform byte count mismatch: expected $ExpectedPayloadBytes, block contains $payloadBytes"
    }

    $payload = [IO.MemoryStream]::new()
    try {
        $remaining = $payloadBytes
        $chunkLimit = [long](1024 * 1024)
        while ($remaining -gt 0) {
            # On the final read, include room for CR/LF so the terminator does
            # not remain queued in front of the next preamble query. USBTMC's
            # native EOM still lets VISA return early when no terminator exists.
            $request = if ($remaining -le $chunkLimit) {
                $remaining + 2
            }
            else {
                $chunkLimit
            }
            try {
                [byte[]]$chunk = $Session.RawIO.Read($request)
            }
            catch {
                $received = $payloadBytes - $remaining
                throw "Timed out reading waveform payload after $received of $payloadBytes bytes: $($_.Exception.Message)"
            }
            if ($chunk.Length -eq 0) {
                throw 'Oscilloscope returned an empty waveform block chunk'
            }
            $take = [int][Math]::Min([long]$chunk.Length, $remaining)
            $payload.Write($chunk, 0, $take)
            $remaining -= $take
        }
        [byte[]]$payloadArray = $payload.ToArray()
    }
    finally {
        $payload.Dispose()
    }

    $block = [IO.MemoryStream]::new()
    try {
        $block.Write($prefix, 0, $prefix.Length)
        $block.Write($lengthBytes, 0, $lengthBytes.Length)
        $block.Write($payloadArray, 0, $payloadArray.Length)
        return $block.ToArray()
    }
    finally {
        $block.Dispose()
    }
}

function Find-TekScope([object]$Manager) {
    foreach ($candidate in $Manager.Find('USB?*INSTR')) {
        if ($candidate -notmatch '::0x0699::') { continue }
        $session = $null
        try {
            $session = Open-Scope $Manager $candidate
            $session.TimeoutMilliseconds = 2500
            $idn = Invoke-Query $session '*IDN?'
            if ($idn.StartsWith('TEKTRONIX,', [StringComparison]::OrdinalIgnoreCase)) {
                return [pscustomobject]@{ resource = [string]$candidate; idn = [string]$idn }
            }
        }
        catch {
            continue
        }
        finally {
            if ($null -ne $session) { $session.Dispose() }
        }
    }
    throw 'SCOPE_NOT_FOUND'
}

function Resolve-ScopeIdentity([object]$Manager, [string]$RequestedResource) {
    if ([string]::IsNullOrWhiteSpace($RequestedResource)) {
        return Find-TekScope $Manager
    }
    $session = $null
    try {
        $session = Open-Scope $Manager $RequestedResource
        $idn = Invoke-Query $session '*IDN?'
        if (-not $idn.StartsWith('TEKTRONIX,', [StringComparison]::OrdinalIgnoreCase)) {
            throw "USB device is not a Tektronix oscilloscope: $idn"
        }
        return [pscustomobject]@{ resource = $RequestedResource; idn = $idn }
    }
    finally {
        if ($null -ne $session) { $session.Dispose() }
    }
}

function Optional-Query(
    [object]$Session,
    [string]$Command,
    [int]$TimeoutMilliseconds = 250
) {
    $savedTimeout = $Session.TimeoutMilliseconds
    try {
        $Session.TimeoutMilliseconds = $TimeoutMilliseconds
        return Invoke-Query $Session $Command
    }
    catch {
        # An unsupported optional query must not leave a late response queued
        # in front of the following waveform preamble query.
        try { $Session.Clear() } catch { }
        return $null
    }
    finally {
        $Session.TimeoutMilliseconds = $savedTimeout
    }
}

function Get-SourceDisplayCommand([string]$Source, [string]$Leaf) {
    if ($Source.StartsWith('MATH')) {
        return "DISPLAY:WAVEVIEW1:MATH:$Source`:$Leaf"
    }
    return "DISPLAY:WAVEVIEW1:$Source`:$Leaf"
}

function Get-SourceLabelCommand([string]$Source) {
    if ($Source.StartsWith('MATH')) {
        return "MATH:$Source`:LABEL:NAME?"
    }
    return "$Source`:LABEL:NAME?"
}

function Get-DisplayedSources([object]$Session, [string[]]$AvailableSources) {
    $visible = [System.Collections.Generic.List[string]]::new()
    foreach ($source in $AvailableSources) {
        $state = Optional-Query $Session (Get-SourceDisplayCommand $source 'STATE?') 500
        if ($null -eq $state) {
            # Older firmware without per-waveview state queries falls back to
            # all CURVE?-capable sources instead of silently dropping data.
            return @($AvailableSources)
        }
        if ([int]$state -ne 0) { $visible.Add($source) }
    }
    if ($visible.Count -eq 0) { throw 'No displayed analog or math waveform source is available' }
    return @($visible.ToArray())
}

function Restore-DataSettings([object]$Session, [hashtable]$Saved) {
    foreach ($item in @(
        @('source', 'DATA:SOURCE'),
        @('encoding', 'DATA:ENCDG'),
        @('width', 'DATA:WIDTH'),
        @('start', 'DATA:START'),
        @('stop', 'DATA:STOP'),
        @('resample', 'DATA:RESAMPLE')
    )) {
        $value = $Saved[$item[0]]
        if (-not [string]::IsNullOrWhiteSpace([string]$value)) {
            try { Write-Command $Session "$($item[1]) $value" } catch { }
        }
    }
}

function Read-ScopeWaveforms([object]$Manager, [object]$Identity, [string]$Destination) {
    if ([string]::IsNullOrWhiteSpace($Destination)) { throw 'Waveform output directory is missing' }
    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    $session = Open-Scope $Manager $Identity.resource
    $resumeAcquisition = $false
    try {
        # A scope in Normal trigger mode commonly remains armed after the last
        # completed acquisition. The displayed record is still valid and must
        # be readable without asking the operator to press Stop. Freeze the
        # record for the multi-channel transfer so a new trigger cannot mix
        # samples from different acquisitions, then restore the armed state in
        # the outer finally block.
        $acquisitionState = [int](Invoke-Query $session 'ACQUIRE:STATE?')
        $resumeAcquisition = ($acquisitionState -ne 0)
        if ($resumeAcquisition) {
            Write-Command $session 'ACQUIRE:STATE STOP'
            $acquisitionStopped = $false
            for ($attempt = 0; $attempt -lt 40; $attempt++) {
                if ([int](Invoke-Query $session 'ACQUIRE:STATE?') -eq 0) {
                    $acquisitionStopped = $true
                    break
                }
                Start-Sleep -Milliseconds 50
            }
            if (-not $acquisitionStopped) {
                throw 'Oscilloscope acquisition could not be paused for waveform transfer'
            }
        }
        $sourceText = Invoke-Query $session 'DATA:SOURCE:AVAILABLE?'
        $availableSources = @($sourceText -split '[,;]' | ForEach-Object { $_.Trim().ToUpperInvariant() } | Where-Object { $_ -match '^(CH\d+|MATH\d+)$' })
        if ($availableSources.Count -eq 0) { throw 'No analog or math waveform source is available' }
        $sources = @(Get-DisplayedSources $session $availableSources)
        $saved = @{
            source = Invoke-Query $session 'DATA:SOURCE?'
            encoding = Invoke-Query $session 'DATA:ENCDG?'
            width = Invoke-Query $session 'DATA:WIDTH?'
            start = Invoke-Query $session 'DATA:START?'
            stop = Invoke-Query $session 'DATA:STOP?'
            resample = Optional-Query $session 'DATA:RESAMPLE?' 500
        }
        $recordLength = [long](Invoke-Query $session 'HORIZONTAL:MODE:RECORDLENGTH?')
        if ($recordLength -le 0) { throw 'Oscilloscope returned an invalid record length' }
        $items = [System.Collections.Generic.List[object]]::new()
        try {
            # Full-resolution means every acquired sample in the current
            # record. Do not inherit a previous controller's resampling ratio.
            Write-Command $session 'DATA:RESAMPLE 1'
            for ($index = 0; $index -lt $sources.Count; $index++) {
                $source = $sources[$index]
                Write-ProgressLine $index $sources.Count "Reading scope $source..."
                Write-Command $session "DATA:SOURCE $source"
                if ($source.StartsWith('MATH')) {
                    # 4/5/6 Series MATH records are always four-byte floating
                    # point values. An integer encoding can leave CURVE?
                    # waiting indefinitely even though preamble queries work.
                    Write-Command $session 'DATA:WIDTH 4'
                    Write-Command $session 'DATA:ENCDG SFPBINARY'
                }
                else {
                    Write-Command $session 'DATA:WIDTH 2'
                    # Changing DATA:WIDTH resets the integer format to RP. Set
                    # signed/little-endian encoding afterwards.
                    Write-Command $session 'DATA:ENCDG SRIBINARY'
                }
                # DATA:START/STOP must be established before NR_PT is queried.
                # NR_PT describes the next CURVE? response, not necessarily the
                # acquisition record length left by another controller.
                Write-Command $session 'DATA:START 1'
                Write-Command $session "DATA:STOP $recordLength"
                $points = [long](Invoke-Query $session 'WFMOUTPRE:NR_PT?')
                if ($points -ne $recordLength) {
                    throw "$source waveform is incomplete: record length $recordLength, transferable points $points"
                }
                $scale = Optional-Query $session (Get-SourceDisplayCommand $source 'VERTICAL:SCALE?') 500
                $position = Optional-Query $session (Get-SourceDisplayCommand $source 'VERTICAL:POSITION?') 500
                $item = [ordered]@{
                    source = $source
                    file = "$source.bin"
                    points = $points
                    x_increment = [double](Invoke-Query $session 'WFMOUTPRE:XINCR?')
                    x_zero = [double](Invoke-Query $session 'WFMOUTPRE:XZERO?')
                    point_offset = [double](Invoke-Query $session 'WFMOUTPRE:PT_OFF?')
                    y_multiplier = [double](Invoke-Query $session 'WFMOUTPRE:YMULT?')
                    y_zero = [double](Invoke-Query $session 'WFMOUTPRE:YZERO?')
                    y_offset = [double](Invoke-Query $session 'WFMOUTPRE:YOFF?')
                    byte_width = [int](Invoke-Query $session 'WFMOUTPRE:BYT_NR?')
                    binary_format = Invoke-Query $session 'WFMOUTPRE:BN_FMT?'
                    byte_order = Invoke-Query $session 'WFMOUTPRE:BYT_OR?'
                    unit = Invoke-Query $session 'WFMOUTPRE:YUNIT?'
                    label = Optional-Query $session (Get-SourceLabelCommand $source) 500
                    scale = $scale
                    position = $position
                    formula = $null
                    inverted = $false
                }
                if ($source.StartsWith('MATH')) {
                    $item.formula = Optional-Query $session "MATH:$source`:DEFINE?" 500
                }
                else {
                    $invert = Optional-Query $session "$source`:INVERT?" 250
                    $item.inverted = ($null -ne $invert -and [int]$invert -ne 0)
                }
                Write-Command $session 'CURVE?'
                $savedTransferTimeout = $session.TimeoutMilliseconds
                try {
                    # A longer ceiling is needed for full-resolution 32-bit
                    # MATH records. It does not delay successful transfers.
                    $session.TimeoutMilliseconds = 60000
                    [byte[]]$waveform = Read-IeeeBinaryBlock $session ([long]($points * $item.byte_width))
                }
                finally {
                    $session.TimeoutMilliseconds = $savedTransferTimeout
                }
                [IO.File]::WriteAllBytes((Join-Path $Destination $item.file), $waveform)
                $items.Add([pscustomobject]$item)
            }
            Write-ProgressLine $sources.Count $sources.Count 'Scope waveform transfer complete'
        }
        finally {
            Restore-DataSettings $session $saved
        }
        return [ordered]@{
            resource = $Identity.resource
            idn = $Identity.idn
            record_length = $recordLength
            available_sources = $availableSources
            horizontal_scale = Optional-Query $session 'HORIZONTAL:MODE:SCALE?'
            horizontal_position = Optional-Query $session 'HORIZONTAL:POSITION?'
            horizontal_delay = Optional-Query $session 'HORIZONTAL:DELAY:TIME?'
            acquisition_was_running = $resumeAcquisition
            sources = $items
        }
    }
    finally {
        try {
            if ($resumeAcquisition) {
                # ACQUIRE:STATE is independent of trigger mode and STOPAFTER;
                # restoring the binary state re-arms the existing Normal/
                # continuous or single-sequence setup without changing it.
                Write-Command $session 'ACQUIRE:STATE 1'
            }
        }
        finally {
            $session.Dispose()
        }
    }
}

function Test-JsonValue([object]$Value) {
    return $null -ne $Value -and [double]::IsNaN([double]$Value) -eq $false -and [double]::IsInfinity([double]$Value) -eq $false
}

function Sync-Scope([object]$Manager, [object]$Identity, [string]$JsonPath) {
    if (-not (Test-Path -LiteralPath $JsonPath)) { throw 'Scope synchronization state file is missing' }
    $state = Get-Content -LiteralPath $JsonPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $start = [double]$state.x_start_s
    $stop = [double]$state.x_stop_s
    if ($stop -le $start) { throw 'The software waveform window is invalid' }
    $recordStart = [double]$state.record_start_s
    $recordStop = [double]$state.record_stop_s
    if ($recordStop -le $recordStart) { throw 'The software full-record window is invalid' }
    $zoomEnabled = $state.zoom_enabled -ne $false
    $syncCursors = $state.sync_cursors -ne $false
    $scale = ($stop - $start) / 10.0
    $center = ($start + $stop) / 2.0
    $position = 100.0 * ($center - $recordStart) / ($recordStop - $recordStart)
    $position = [Math]::Max(0.0, [Math]::Min(100.0, $position))
    $session = Open-Scope $Manager $Identity.resource
    try {
        # Keep the acquisition timebase untouched. The built-in Zoom1 view
        # retains the full-record overview and gives the operator a one-click
        # path back to the original waveform by closing Zoom on the scope.
        $zoom = 'DISPLAY:WAVEVIEW1:ZOOM:ZOOM1'
        if (-not $zoomEnabled) {
            Write-Command $session "$zoom`:STATE OFF"
            $zoomState = [int](Invoke-Query $session "$zoom`:STATE?")
            if ($zoomState -ne 0) { throw 'Oscilloscope did not disable the Zoom1 view' }
            return [ordered]@{
                resource = $Identity.resource
                idn = $Identity.idn
                synced = $true
                zoom_enabled = $false
            }
        }
        Write-Command $session ("$zoom`:HORIZONTAL:WINSCALE {0:R}" -f $scale)
        Write-Command $session ("$zoom`:HORIZONTAL:POSITION {0:R}" -f $position)
        Write-Command $session "$zoom`:STATE ON"
        if ($syncCursors) {
            $base = 'DISPLAY:WAVEVIEW1:CURSOR:CURSOR1'
            # SCREEN cursors are the scope equivalent of the app's independent
            # A/B vertical lines plus Ha/Hb horizontal lines. Their X/Y positions
            # are still expressed in the selected sources' physical units.
            Write-Command $session "$base`:FUNCTION SCREEN"
            Write-Command $session "$base`:MODE INDEPENDENT"
            $sourceA = [string]$state.source_a
            $sourceB = [string]$state.source_b
            if (-not [string]::IsNullOrWhiteSpace($sourceA) -and -not [string]::IsNullOrWhiteSpace($sourceB)) {
                $splitMode = if ($sourceA -eq $sourceB) { 'SAME' } else { 'SPLIT' }
                Write-Command $session "$base`:SPLITMODE $splitMode"
            }
            # Changing split mode resets source assignments on MSO4B. Apply the
            # A/B sources afterwards so independent Ha/Hb bindings survive.
            if (-not [string]::IsNullOrWhiteSpace($sourceA)) { Write-Command $session "$base`:ASOURCE $sourceA" }
            if (-not [string]::IsNullOrWhiteSpace($sourceB)) { Write-Command $session "$base`:BSOURCE $sourceB" }
            if (Test-JsonValue $state.cursor_a_s) { Write-Command $session ("$base`:SCREEN:AXPOSITION {0:R}" -f [double]$state.cursor_a_s) }
            if (Test-JsonValue $state.cursor_b_s) { Write-Command $session ("$base`:SCREEN:BXPOSITION {0:R}" -f [double]$state.cursor_b_s) }
            if (-not [string]::IsNullOrWhiteSpace($sourceA) -and (Test-JsonValue $state.level_a)) { Write-Command $session ("$base`:SCREEN:AYPOSITION {0:R}" -f [double]$state.level_a) }
            if (-not [string]::IsNullOrWhiteSpace($sourceB) -and (Test-JsonValue $state.level_b)) { Write-Command $session ("$base`:SCREEN:BYPOSITION {0:R}" -f [double]$state.level_b) }
            Write-Command $session "$base`:STATE ON"
        }
        $zoomState = [int](Invoke-Query $session "$zoom`:STATE?")
        if ($zoomState -eq 0) { throw 'Oscilloscope did not enable the Zoom1 view' }
        return [ordered]@{
            resource = $Identity.resource
            idn = $Identity.idn
            synced = $true
            zoom_enabled = $true
            zoom_winscale = [double](Invoke-Query $session "$zoom`:HORIZONTAL:WINSCALE?")
            zoom_position = [double](Invoke-Query $session "$zoom`:HORIZONTAL:POSITION?")
        }
    }
    finally {
        $session.Dispose()
    }
}

$manager = $null
try {
    $manager = Open-VisaManager
    $identity = Resolve-ScopeIdentity $manager $Resource
    switch ($Operation) {
        'discover' { Write-Result $identity }
        'acquire' { Write-Result (Read-ScopeWaveforms $manager $identity $OutputPath) }
        'sync' { Write-Result (Sync-Scope $manager $identity $StatePath) }
    }
}
catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
finally {
    if ($null -ne $manager) { $manager.Dispose() }
}

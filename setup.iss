[Setup]
AppName=CraftCloud
AppVersion=2.0.0
DefaultDirName={autopf}\CraftCloud
DefaultGroupName=CraftCloud
OutputDir=.\installer_output
OutputBaseFilename=CraftCloud_Setup
Compression=lzma2
SolidCompression=yes
SetupIconFile=resources\cc.ico
UninstallDisplayName=CraftCloud
PrivilegesRequired=lowest

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "dist\CraftCloud\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Tasks]
Name: "startup"; Description: "Start CraftCloud on system startup"; GroupDescription: "System startup"; Flags: checkedonce

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "CraftCloud"; ValueData: "{app}\CraftCloud.exe"; Flags: uninsdeletevalue

[Icons]
Name: "{commondesktop}\CraftCloud"; Filename: "{app}\CraftCloud.exe"
Name: "{group}\CraftCloud"; Filename: "{app}\CraftCloud.exe"
Name: "{group}\Uninstall CraftCloud"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\CraftCloud.exe"; Description: "Launch CraftCloud"; Flags: nowait postinstall skipifsilent
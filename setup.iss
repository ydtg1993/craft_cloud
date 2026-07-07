[Setup]
AppName=CraftCloud
AppVersion=2.7.7
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

[InstallDelete]
; 清除旧 session（每次安装重新登录）
Type: files; Name: "{app}\sessions\my_account.session"
Type: files; Name: "{app}\sessions\my_account.session-wal"
Type: files; Name: "{app}\sessions\my_account.session-shm"
; 清除旧单实例锁（升级后旧 PID 一定过期）
Type: files; Name: "{app}\data\.instance.lock"

[Tasks]
Name: "startup"; Description: "Start CraftCloud on system startup"; GroupDescription: "System startup"; Flags: checkedonce

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "CraftCloud"; ValueData: "{app}\CraftCloud.exe"; Flags: uninsdeletevalue; Tasks: startup

[Icons]
Name: "{userdesktop}\CraftCloud"; Filename: "{app}\CraftCloud.exe"
Name: "{group}\CraftCloud"; Filename: "{app}\CraftCloud.exe"
Name: "{group}\Uninstall CraftCloud"; Filename: "{uninstallexe}"

[UninstallDelete]
; 卸载时清理运行时产生的用户数据
Type: filesandordirs; Name: "{app}\data"
Type: filesandordirs; Name: "{app}\sessions"
Type: files; Name: "{app}\config\config.yaml"

[Run]
Filename: "{app}\CraftCloud.exe"; Description: "Launch CraftCloud"; Flags: nowait postinstall skipifsilent
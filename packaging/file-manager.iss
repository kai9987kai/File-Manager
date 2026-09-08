#ifndef AppVersion
  #error AppVersion must be supplied by build_release.py
#endif
#ifndef BundleDir
  #error BundleDir must be supplied by build_release.py
#endif
#ifndef ReleaseDir
  #error ReleaseDir must be supplied by build_release.py
#endif
#ifndef ProjectDir
  #error ProjectDir must be supplied by build_release.py
#endif

[Setup]
AppId={{7F35C649-67EE-4C52-920A-A86328799E1D}
AppName=File Manager
AppVersion={#AppVersion}
AppVerName=File Manager {#AppVersion}
AppPublisher=File Manager contributors
AppPublisherURL=https://github.com/kai9987kai/File-Manager
AppSupportURL=https://github.com/kai9987kai/File-Manager/issues
VersionInfoVersion={#AppVersion}
VersionInfoDescription=File Manager {#AppVersion} Setup
DefaultDirName={localappdata}\Programs\FileManager
DefaultGroupName=File Manager
AllowNoIcons=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir={#ReleaseDir}
OutputBaseFilename=FileManager-{#AppVersion}-Windows-x64-Setup
SetupIconFile={#ProjectDir}\app\assets\file-manager.ico
UninstallDisplayIcon={app}\FileManager.exe
UninstallDisplayName=File Manager {#AppVersion}
LicenseFile={#ProjectDir}\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
CloseApplications=no
RestartApplications=no
CreateUninstallRegKey=not IsSmokeInstall

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"; Flags: unchecked

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\File Manager"; Filename: "{app}\FileManager.exe"; WorkingDir: "{userdocs}"; Check: not IsSmokeInstall
Name: "{group}\Uninstall File Manager"; Filename: "{uninstallexe}"; Check: not IsSmokeInstall
Name: "{autodesktop}\File Manager"; Filename: "{app}\FileManager.exe"; WorkingDir: "{userdocs}"; Tasks: desktopicon; Check: not IsSmokeInstall

[Run]
Filename: "{app}\FileManager.exe"; Description: "Launch File Manager"; Flags: nowait postinstall skipifsilent; Check: not IsSmokeInstall

[Code]
function IsSmokeInstall: Boolean;
begin
  { Packaging tests use the exact installer but keep registration/shortcuts isolated. }
  Result := ExpandConstant('{param:PACKAGINGSMOKE|0}') = '1';
end;

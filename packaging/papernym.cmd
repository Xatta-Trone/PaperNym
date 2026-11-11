@echo off
rem PaperNym command line: runs papernym-cli.exe from the install folder.
"%~dp0..\papernym-cli.exe" %*
exit /b %ERRORLEVEL%

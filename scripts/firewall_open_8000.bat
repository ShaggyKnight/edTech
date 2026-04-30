@echo off
REM Abre el puerto 8000 en el Firewall de Windows para que el dev server
REM Django sea accesible desde otros equipos en la red local (LAN).
REM
REM USO:
REM   1. Click derecho sobre este archivo
REM   2. "Ejecutar como administrador"
REM
REM Para REVERTIR (quitar la regla): correr scripts\firewall_close_8000.bat

echo.
echo Agregando regla al Firewall de Windows: TCP puerto 8000 (Private + Domain).
echo.

netsh advfirewall firewall add rule ^
    name="Ideas Boutique - Django Dev 8000" ^
    description="Permite acceso al dev server Django desde la red local" ^
    dir=in action=allow protocol=TCP localport=8000 ^
    profile=private,domain

if %errorlevel% equ 0 (
    echo.
    echo OK: regla agregada. Ahora podes acceder al server desde otros
    echo dispositivos en la misma red (celular, laptop, etc).
    echo.
) else (
    echo.
    echo ERROR: no se pudo agregar la regla. Asegurate de ejecutar este
    echo .bat como Administrador (click derecho - Ejecutar como administrador).
    echo.
)
pause

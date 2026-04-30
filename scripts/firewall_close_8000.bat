@echo off
REM Quita la regla que abre el puerto 8000 en el Firewall de Windows.
REM
REM USO:
REM   1. Click derecho sobre este archivo
REM   2. "Ejecutar como administrador"

echo.
echo Quitando regla "Ideas Boutique - Django Dev 8000" del Firewall.
echo.

netsh advfirewall firewall delete rule name="Ideas Boutique - Django Dev 8000"

if %errorlevel% equ 0 (
    echo.
    echo OK: regla eliminada. El puerto 8000 ya no acepta conexiones desde
    echo otros equipos de la red.
    echo.
) else (
    echo.
    echo ERROR: no se pudo quitar la regla. Verifica que existia (puede que
    echo ya este eliminada) y que ejecutaste como Administrador.
    echo.
)
pause

# AutoNext en Linux (Debian)

Guía para correr AutoNext en Debian 12 (Bookworm) o Debian 13 (Trixie). También sirve para Ubuntu y Linux Mint.

## Qué se necesita

| Qué | Para qué | Paquete |
|-----|----------|---------|
| Python 3.10 o más nuevo | el programa | `python3` (Debian 12 trae 3.11, Debian 13 trae 3.13) |
| venv | entorno aislado con las librerías | `python3-venv` |
| Tkinter | ventana del panel de escritorio | `python3-tk` |
| Brave | el navegador donde se reproducen los capítulos | `brave-browser` (repositorio de Brave) |
| Node.js 18 o más nuevo + npm | solo para compilar la app del celular | `nodejs`, `npm` |
| Escritorio gráfico (X11 o Wayland) | Brave se abre en una ventana real | GNOME, KDE, XFCE… |

Librerías de Python (se instalan solas desde `requirements.txt`):

- `playwright`: controla Brave.
- `customtkinter`: el panel.
- `qrcode[pil]`: el QR del control móvil.
- `keyring`: guarda las contraseñas de los sitios en el llavero del sistema.

Espacio aproximado: ~150 MB de Python/venv, ~110 MB de Brave, ~40 MB de `web/node_modules`.

No hace falta `playwright install` ni descargar Chromium. AutoNext usa el Brave instalado en el sistema.

## 1. Paquetes del sistema

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-tk curl
```

Node.js solo hace falta si `web/dist` no existe o si cambias el código de la app del celular:

```bash
sudo apt install -y nodejs npm
node --version   # debe ser 18 o más
```

## 2. Instalar Brave

Repositorio oficial de Brave (instrucciones de https://brave.com/linux/):

```bash
sudo curl -fsSLo /usr/share/keyrings/brave-browser-archive-keyring.gpg https://brave-browser-apt-release.s3.brave.com/brave-browser-archive-keyring.gpg
sudo curl -fsSLo /etc/apt/sources.list.d/brave-browser-release.sources https://brave-browser-apt-release.s3.brave.com/brave-browser.sources
sudo apt update
sudo apt install -y brave-browser
```

AutoNext busca Brave solo en estas rutas: `brave-browser`, `brave`, `/opt/brave.com/brave/brave`, `/snap/bin/brave` y el Flatpak `com.brave.Browser`. Si lo tienes en otro lugar, pon la ruta en el panel, pestaña **Navegador → Ruta de Brave**.

## 3. Copiar el proyecto

Copia la carpeta del proyecto a Linux (USB, `scp`, git…). **No copies** estas carpetas:

- `brave_profile/`: perfil de Brave de Windows (~500 MB), no sirve en Linux; se crea solo.
- `__pycache__/`, `.venv/`
- `web/node_modules/`: se reinstala si hace falta.

Sí copia `perfiles.json`: tiene tus perfiles, el progreso y el token del QR. La ruta de Brave de Windows que trae guardada se ignora sola, porque si no existe AutoNext busca Brave automáticamente.

Ejemplo con `rsync` desde otra PC Linux o desde WSL:

```bash
rsync -av --exclude brave_profile --exclude __pycache__ --exclude .venv --exclude web/node_modules "cambiar capitulo/" usuario@debian:~/autonext/
```

## 4. Primera ejecución

```bash
cd ~/autonext
chmod +x iniciar.sh
./iniciar.sh
```

La primera vez, `iniciar.sh`:

1. Crea `.venv/` e instala `requirements.txt` (1–2 min).
2. Si falta `web/dist/index.html` y hay `npm`, compila la app del celular.
3. Abre el panel de escritorio y el servidor del celular.

Las siguientes veces solo arranca.

Modo sin panel (solo control desde el celular; Brave sigue necesitando escritorio):

```bash
./iniciar.sh --web
```

En la terminal aparece `Control movil: http://192.168.x.x:8765/?t=...`.

## 5. Control desde el celular

- El panel muestra el QR en la tarjeta **📱 CONTROL MÓVIL**. Escanéalo con el celular conectado a la **misma red Wi-Fi**.
- El QR cambia solo si cambia la IP de la PC. El token es fijo (`settings.token` en `perfiles.json`).
- Si Debian tiene firewall activo (`ufw`), abre el puerto:

```bash
sudo ufw allow 8765/tcp
```

## Cuentas de sitios (Crunchyroll, etc.)

En el panel, pestaña **Sitio → 🔑 Cuenta del sitio**: escribe usuario y contraseña y pulsa **Guardar**. AutoNext inicia sesión solo cuando el sitio lo pida.

- La contraseña va al llavero del sistema (GNOME Keyring / KWallet, a través de `keyring`). En Debian con escritorio ya viene instalado.
- Sin llavero (servidor sin escritorio) se guarda en `credenciales.json`, con permisos `600` y excluido de git por `.gitignore`.
- Nunca se guarda en `perfiles.json` y el celular no la ve.
- Si el sitio muestra un captcha, resuélvelo a mano en la ventana de Brave. AutoNext espera hasta 40 s.

## 6. Actualizar dependencias

`iniciar.sh` solo instala librerías cuando crea `.venv`. Si `requirements.txt` cambia (por ejemplo cuando se añadió `qrcode`):

```bash
cd ~/autonext
.venv/bin/pip install -r requirements.txt
```

Si cambias algo en `web/src`, recompila la app del celular:

```bash
cd ~/autonext/web && npm install && npm run build
```

Para empezar de cero, borra `.venv` y vuelve a correr `./iniciar.sh`.

## 7. Arrancar solo al iniciar sesión (opcional)

Crea `~/.config/autostart/autonext.desktop`:

```ini
[Desktop Entry]
Type=Application
Name=AutoNext
Exec=/home/USUARIO/autonext/iniciar.sh
Path=/home/USUARIO/autonext
Terminal=false
```

Cambia `USUARIO` por tu usuario.

## Problemas comunes

| Síntoma | Causa / solución |
|---------|------------------|
| `ModuleNotFoundError: No module named 'tkinter'` | `sudo apt install python3-tk`, luego borrar `.venv` y correr de nuevo |
| `No module named 'qrcode'` | `.venv/bin/pip install -r requirements.txt` |
| `ensurepip is not available` al crear `.venv` | `sudo apt install python3-venv` |
| No abre Brave / "No such file" | instalar Brave (paso 2) o poner la ruta en **Navegador → Ruta de Brave** |
| El celular dice "Falta compilar la app movil" | `sudo apt install nodejs npm`, luego `cd web && npm install && npm run build` |
| El celular no conecta | misma Wi-Fi, `sudo ufw allow 8765/tcp`, revisar la IP que muestra el panel |
| `Address already in use` (puerto 8765 o 9222) | ya hay otro AutoNext o Brave con depuración abierto: cerrarlo o cambiar puertos en **Navegador** |
| Error de display en un servidor sin escritorio | AutoNext necesita sesión gráfica: Brave no corre en modo headless |

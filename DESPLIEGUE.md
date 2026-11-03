# Despliegue gratuito: que la web abra desde un enlace y no se duerma

Tres servicios gratuitos, sin instalar nada en su PC y sin compilar:

| Servicio | Para qué | Costo |
|---|---|---|
| **Neon** | Base de datos Postgres en la nube (los datos sobreviven a los reinicios) | Gratis |
| **Render** | Corre la web y el bot (procesos separados dentro del mismo servicio) | Gratis |
| **UptimeRobot** | Hace ping cada 5 minutos para que Render no duerma el servicio y envía un correo si se cae | Gratis |

> Vercel no sirve para este proyecto: ejecuta funciones que viven segundos, y la web (Streamlit) y el bot necesitan un servidor encendido.

Tiempo estimado: 15 minutos. Necesita una cuenta de GitHub (ya tiene el repositorio) y un correo.

## 1. Base de datos (Neon)
1. Entre a https://neon.tech e inicie sesión con GitHub.
2. *Create project*; elija la región más cercana (por ejemplo, São Paulo).
3. Copie la **connection string** (empieza con `postgresql://` y termina con `?sslmode=require`). Las tablas las crea la aplicación sola.

## 2. Bot de Telegram
Use un token para la nube. **Un mismo token no puede ser atendido por dos servidores a la vez**: si probó el bot en su PC, deténgalo
(cierre `bot.py`) o cree otro bot con @BotFather (`/newbot`) para la nube. Si el token se expuso antes, revóquelo con `/revoke`.

## 3. Web y bot (Render)
1. Entre a https://render.com e inicie sesión con GitHub.
2. *New* → *Blueprint* → elija este repositorio. Render lee `render.yaml`.
3. Complete las variables secretas que pide:
   - `DATABASE_URL`: la cadena de Neon.
   - `TELEGRAM_BOT_TOKEN`: el token del bot.
   - `APP_PASSWORD`: una contraseña para entrar a la web (obligatoria: la web maneja datos de pacientes).
   - `TWILIO_*`: opcionales (SMS y llamadas); déjelas vacías si no las usa.
4. *Apply*. La primera construcción tarda unos minutos. Al terminar tendrá un enlace como `https://gestion-inasistencias.onrender.com`.

## 4. Que no se duerma (UptimeRobot)
1. Entre a https://uptimerobot.com y cree una cuenta.
2. *Add new monitor* → tipo **HTTP(s)** → URL: `https://<su-app>.onrender.com/_stcore/health` → intervalo **5 minutos**.
3. En *Alert contacts*, deje su correo: recibirá un aviso si el servicio se cae.

## 5. Comprobar
Abra el enlace, ingrese la contraseña y verifique en la barra lateral: **Canales: Telegram** y **Servicio del bot: activo**
(puede tardar un minuto). Luego registre un paciente en *Admisión de pacientes*.

## Qué tener en cuenta
- Los planes gratuitos pueden cambiar sus condiciones y no tienen garantía de disponibilidad. Con el ping cada 5 minutos el servicio se
  mantiene despierto; si se reinicia, el bot vuelve solo y los datos siguen en Neon.
- El plan gratuito de Render tiene 512 MB de memoria. Por eso en la nube la explicación de cada caso usa un cálculo liviano
  (`NOSHOW_SIN_SHAP=1`) en lugar de SHAP.
- Twilio (cuenta de prueba) solo envía a números verificados.
- Con pacientes reales, los datos quedan en servicios de terceros: se requiere la autorización institucional y la aprobación de un
  comité de ética antes de usarlo fuera de una demostración.

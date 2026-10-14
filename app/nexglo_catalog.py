"""NexgloTV business catalog: packages, device options, and bilingual UI strings.

Everything customer-facing lives here. No barbershop references.
"""

from __future__ import annotations

from typing import Optional

# --- Subscription packages ----------------------------------------------------
# Kept for reference; actual pricing is in nexglo_pricing.py
PACKAGE_MONTHS = (1, 3, 6, 12)

# --- Device platforms ---------------------------------------------------------
# Customer-facing device options for the device selection step
DEVICE_PLATFORMS = [
    {"id": "android_phone", "label": "Android phone", "os": "Android"},
    {"id": "iphone_ipad", "label": "iPhone / iPad", "os": "iOS / iPadOS"},
    {"id": "smart_tv", "label": "Smart TV (Samsung/LG/Android TV/other)", "os": "Tizen / webOS / Android TV"},
    {"id": "fire_stick", "label": "Fire Stick / Fire TV", "os": "Fire OS"},
    {"id": "tablet", "label": "Tablet (Android/iPad)", "os": "Android / iPadOS"},
    {"id": "laptop", "label": "Laptop / Desktop (Windows/Mac)", "os": "Windows / macOS"},
    {"id": "android_tv_box", "label": "Android TV Box", "os": "Android TV"},
    {"id": "roku", "label": "Roku TV / Roku Box", "os": "Roku OS"},
    {"id": "other", "label": "Other — I'll describe it", "os": "Unknown"},
]

DEVICE_BY_ID = {d["id"]: d for d in DEVICE_PLATFORMS}


def get_device(device_id: str) -> Optional[dict]:
    return DEVICE_BY_ID.get(device_id)


def device_label(device_id: str) -> str:
    d = DEVICE_BY_ID.get(device_id)
    return d["label"] if d else device_id


# --- Installation methods -----------------------------------------------------
INSTALL_METHODS = [
    {"id": "self_install", "label": "Self-install with free remote guidance", "has_fee": False},
    {"id": "staff_visit", "label": "Staff visit (location-based fee may apply)", "has_fee": True},
]

INSTALL_BY_ID = {m["id"]: m for m in INSTALL_METHODS}


# --- Bilingual copy -----------------------------------------------------------
# Values are (es, en). Use t(key, lang, **kwargs) to render with .format().
# Button titles must fit in 20 chars, list row titles in 24.
STRINGS: dict[str, tuple[str, str]] = {
    # ---------------------------------------------------------------- menu
    "menu_body": (
        "¡Hola! 👋 Soy el asistente de NexgloTV. ¿En qué te ayudo hoy?",
        "Hi! 👋 I'm the NexgloTV assistant. How can I help today?",
    ),
    "menu_packages": ("Ver paquetes", "View packages"),
    "menu_devices": ("Dispositivos y apps", "Devices & installation"),
    "menu_renewal": ("Renovar suscripción", "Renew subscription"),
    "menu_support": ("Soporte técnico", "Technical support"),
    "menu_human": ("Hablar con alguien", "Talk to a person"),
    "menu_main": ("Menú principal", "Main menu"),
    "menu_button": ("Ver opciones", "See options"),
    "menu_section": ("Opciones", "Options"),

    # -------------------------------------------------------------- pricing
    "price_prompt": (
        "Aquí tienes nuestros paquetes con **20% de descuento** 📺\n\n"
        "¿Qué opción te interesa?",
        "Here are our packages with **20% OFF** 📺\n\n"
        "Which option would you like?",
    ),
    "price_only": (
        "Entendido. Aquí están los precios con 20% de descuento:\n\n{price_card}\n\n"
        "¿Qué paquete te gustaría?",
        "Understood. Here are the prices with 20% off:\n\n{price_card}\n\n"
        "Which package would you like?",
    ),

    # ---------------------------------------------------------- package select
    "choose_package": (
        "Perfecto. ¿Qué duración y cuántos dispositivos?",
        "Great. What duration and how many devices?",
    ),
    "package_button": ("Elegir paquete", "Choose package"),
    "package_section": ("Paquetes", "Packages"),

    # ----------------------------------------------------------- quote
    "quote_body": (
        "👍 **{months} mes{months_plural} para {devices} dispositivo{devices_plural}** cuesta **{total}**.\n\n"
        "Podemos ayudarte a instalar y probar el servicio **antes de pagar** la suscripción.\n"
        "¿Te parece bien pagar una vez confirmemos que todo funciona?",
        "👍 **{months} month{months_plural} for {devices} device{devices_plural}** costs **{total}**.\n\n"
        "We can help you install and test the service **before you pay** for the subscription.\n"
        "Are you comfortable paying once we confirm it works?",
    ),
    "quote_ready_yes": ("Sí, listo para pagar", "Yes, ready to pay"),
    "quote_ready_no": ("Lo voy a pensar", "Let me think"),
    "quote_change": ("Cambiar paquete", "Change package"),

    # ---------------------------------------------------------- device select
    "choose_device": (
        "¿En qué dispositivo vas a ver NexgloTV?\n\n"
        "1️⃣ Android phone\n2️⃣ iPhone / iPad\n3️⃣ Smart TV\n4️⃣ Fire Stick\n"
        "5️⃣ Tablet\n6️⃣ Laptop\n7️⃣ Android TV Box\n8️⃣ Roku\n\n"
        "Responde con el número o dime el modelo.",
        "Which device will you watch NexgloTV on?\n\n"
        "1️⃣ Android phone\n2️⃣ iPhone / iPad\n3️⃣ Smart TV\n4️⃣ Fire Stick\n"
        "5️⃣ Tablet\n6️⃣ Laptop\n7️⃣ Android TV Box\n8️⃣ Roku\n\n"
        "Reply with the number or tell me the model.",
    ),
    "device_button": ("Elegir dispositivo", "Choose device"),
    "device_section": ("Dispositivos", "Devices"),
    "device_model_prompt": (
        "Gracias. ¿Cuál es el modelo exacto? (ej. Samsung 55\" TU7000, Fire Stick 4K, iPhone 14)",
        "Thanks. What's the exact model? (e.g. Samsung 55\" TU7000, Fire Stick 4K, iPhone 14)",
    ),

    # -------------------------------------------------------- install method
    "choose_install": (
        "Podemos guiarte en la instalación **gratis** antes del pago 😊.\n"
        "Si prefieres que nuestro equipo te visite, puede haber un cargo adicional por desplazamiento.\n\n"
        "¿Prefieres instalar tú mismo con nuestra ayuda o agendar una visita?",
        "We can guide you through installation **for free** before payment 😊.\n"
        "If you'd prefer our team to visit, a location-based service fee may apply.\n\n"
        "Would you rather self-install with our help or arrange a visit?",
    ),
    "install_self": ("Instalar yo (gratis)", "Self-install (free)"),
    "install_visit": ("Visita del equipo", "Staff visit (fee)"),
    "area_prompt": (
        "Entendido. ¿En qué zona/ciudad estás? El equipo confirmará el cargo exacto antes de agendar.",
        "Got it. What area/city are you in? The team will confirm the exact fee before booking.",
    ),
    "visit_fee_note": (
        "⚠️ El cargo por visita es adicional a la suscripción. El equipo te dará el monto exacto según tu zona.",
        "⚠️ Visit fee is additional to the subscription. The team will quote the exact amount for your area.",
    ),

    # ------------------------------------------------------------ app link
    "app_link_sent": (
        "Para tu **{device}**, instala **{app_name}** desde:\n{app_url}\n\n"
        "Cuando puedas abrir la app, responde **INSTALADO** y te conectaré con el equipo de configuración para tu acceso.",
        "For your **{device}**, install **{app_name}** from:\n{app_url}\n\n"
        "When you can open the app, reply **INSTALLED** and I'll connect you with the setup team for your login.",
    ),
    "app_link_missing": (
        "Quiero enviarte la app correcta para tu dispositivo, no una genérica.\n"
        "Te conecto con el equipo de configuración para confirmar la app y el enlace oficial.",
        "I want to send you the correct app for your device, not a generic one.\n"
        "Connecting you with the setup team to confirm the supported app and official download link.",
    ),
    "app_installed_prompt": (
        "¿Ya puedes abrir la app? Responde **INSTALADO** cuando esté lista.",
        "Can you open the app now? Reply **INSTALLED** when ready.",
    ),

    # ------------------------------------------------------------ handoff
    "handoff": (
        "Perfecto ✅ Como ya tienes la app instalada, solicito a nuestro equipo de configuración "
        "que te entregue tu acceso y verifique que todo funcione antes del pago de tu suscripción.",
        "Great ✅ Since you have the app installed, I'll request our setup team to provide your "
        "login and verify everything works before your subscription payment.",
    ),
    "handoff_resolved": (
        "El asistente de NexgloTV ha retomado la conversación. 🤖 Si necesitas algo más, escribe *menú*.",
        "The NexgloTV assistant is back. 🤖 If you need anything else, type *menu*.",
    ),

    # --------------------------------------------------------- payment due
    "payment_due": (
        "✅ Tu configuración de NexgloTV está confirmada y funcionando.\n\n"
        "Tu plan de **{months} mes{months_plural} para {devices} dispositivo{devices_plural}** cuesta **{total}**.\n\n"
        "Preferimos **Orange Money**, y también aceptamos AfriMoney, QMoney, transferencia bancaria y efectivo.\n"
        "¿Quieres los datos oficiales de pago?",
        "✅ Your NexgloTV setup is confirmed working.\n\n"
        "Your **{months}-month plan for {devices} device{devices_plural}** costs **{total}**.\n\n"
        "We prefer **Orange Money**, and also support AfriMoney, QMoney, bank transfer and cash.\n"
        "Would you like the official payment details?",
    ),
    "payment_details": (
        "*NexgloTV Pago Oficial*\n"
        "Paquete: {package}\n"
        "Monto: {amount}\n"
        "Orange Money: {orange_number} — {orange_name}\n"
        "Otros métodos verificados: {other_methods}\n\n"
        "Después de pagar, envía la referencia de la transacción para que el equipo confirme el recibo.\n"
        "**Nunca compartas tu PIN u OTP.**",
        "*NexgloTV Official Payment*\n"
        "Package: {package}\n"
        "Amount: {amount}\n"
        "Orange Money: {orange_number} — {orange_name}\n"
        "Other verified methods: {other_methods}\n\n"
        "After paying, send the transaction reference so our team can confirm receipt.\n"
        "**Never share your PIN or OTP.**",
    ),
    "payment_details_missing": (
        "Aceptamos Orange Money (preferido), AfriMoney, QMoney, transferencia bancaria y efectivo.\n"
        "Permíteme obtener los datos oficiales correctos de nuestro equipo — prefiero confirmar antes de enviarte un número equivocado.",
        "We accept Orange Money (preferred), AfriMoney, QMoney, bank transfer and cash.\n"
        "Let me get the correct official account details from our team — I'd rather confirm than send you a wrong number.",
    ),
    "payment_proof_received": (
        "Gracias 🙏 Hemos recibido tu información de pago. Nuestro equipo la verificará contra los registros oficiales antes de confirmar tu suscripción.",
        "Thank you 🙏 We've received your payment information. Our team will verify it against official payment records before confirming your subscription.",
    ),
    "payment_verified": (
        "🎉 ¡Pago confirmado! Tu suscripción de NexgloTV ({package}) ya está activa (vigencia: {expires}). ¡Gracias por elegir NexgloTV!",
        "🎉 Payment confirmed! Your NexgloTV subscription ({package}) is now active (expires: {expires}). Thank you for choosing NexgloTV!",
    ),

    # ------------------------------------------------------------ trials
    "trial_available": (
        "Sí, podemos revisar una prueba gratis antes de pagar 😊.\n"
        "Nuestro equipo necesita confirmar la duración disponible y preparar la cuenta.\n\n"
        "¿En qué dispositivo la usarías?",
        "Yes, we can check a pre-payment free trial 😊.\n"
        "Our team needs to confirm the available trial duration and set up the account.\n\n"
        "Which device would you use?",
    ),
    "trial_offer_hesitant": (
        "Sin presión 😊. Si prefieres ver cómo funciona antes de decidir, podemos revisar si hay una prueba gratis disponible para ti.\n¿Te ayudaría eso?",
        "No pressure 😊. If you'd prefer to see how it works before deciding, we can check whether a free trial is available for you.\nWould that help?",
    ),

    # ------------------------------------------------------- existing customer
    "renewal_prompt": (
        "Veo que ya eres cliente de NexgloTV. ¿Quieres renovar tu suscripción actual o cambiar de paquete?",
        "I see you're already a NexgloTV customer. Would you like to renew your current subscription or change packages?",
    ),
    "renewal_quote": (
        "Tu renovación de **{months} mes{months_plural} para {devices} dispositivo{devices_plural}** sería **{total}**.\n"
        "¿Confirmamos?",
        "Your renewal for **{months} month{months_plural} for {devices} device{devices_plural}** would be **{total}**.\n"
        "Shall we confirm?",
    ),

    # ---------------------------------------------------------- FAQ / info
    "info_prompt": (
        "Claro. Pregúntame lo que quieras: paquetes, precios, dispositivos, instalación, pruebas gratis, pagos, renovaciones o canales. 📺",
        "Sure. Ask me anything: packages, prices, devices, installation, free trials, payments, renewals or channels. 📺",
    ),
    "no_answer": (
        "No encontré información sobre eso. ¿Quieres que te comunique con alguien del equipo de NexgloTV?",
        "I couldn't find anything about that. Would you like me to connect you with someone from the NexgloTV team?",
    ),

    # ------------------------------------------------------ compliance
    "optout_ack": (
        "Entendido. No te enviaremos más mensajes promocionales por este chat. Si cambias de opinión, escribe ALTA (o START). 👋",
        "Understood. We'll stop promotional messages to this chat. If you change your mind, reply START (or ALTA). 👋",
    ),
    "optin_ack": (
        "¡Bienvenido de vuelta! Volverás a recibir nuestras respuestas. 🙌",
        "Welcome back! You'll receive our replies again. 🙌",
    ),

    # -------------------------------------------------------------- fallbacks
    "fallback_prefix": (
        "Esto es lo que encontré:",
        "Here's what I found:",
    ),
    "thanks_reply": (
        "¡Con gusto! 🙌 Si necesitas algo más, escribe *menú*.",
        "You're welcome! 🙌 If you need anything else, type *menu*.",
    ),
    "reset_ack": (
        "Listo, volvamos a empezar. 👋",
        "Done, let's start fresh. 👋",
    ),
    "booking_cancelled": (
        "Proceso cancelado. Si necesitas algo más, escribe *menú*. 👋",
        "Process cancelled. If you need anything else, type *menu*. 👋",
    ),
    "audio_heard": (
        "🎤 Escuché: «{text}»",
        "🎤 Heard: \"{text}\"",
    ),
    "audio_unsupported": (
        "No pude transcribir tu nota de voz. ¿Podrías escribirlo por texto o elegir una opción del menú?",
        "I couldn't transcribe your voice note. Could you type your message or pick an option from the menu?",
    ),
    "image_received": (
        "Recibimos tu imagen. Un miembro de nuestro equipo la revisará enseguida.",
        "We received your image. A team member will review it shortly.",
    ),
    "option_expired": (
        "Esa opción ya no está disponible. 🙏 Te muestro las actuales:",
        "That option is no longer available. 🙏 Here are the current ones:",
    ),

    # ----------------------------------------------------------- channels
    "channels_disclaimer": (
        "Ofrecemos una amplia variedad de deportes y entretenimiento, pero los canales y partidos exactos pueden cambiar.\n"
        "Dime qué canal o competición buscas y te ayudo a verificar su disponibilidad actual.",
        "We offer a wide range of sports and TV entertainment, but exact channels and matches can change.\n"
        "Tell me the channel or competition you want and I'll help check its current availability.",
    ),

    # ----------------------------------------------------------- internet
    "internet_note": (
        "NexgloTV necesita una conexión a internet estable. QCell es una opción local.\n"
        "Unos **3 Mbps** pueden servir para streaming de calidad básica, pero la calidad HD depende de tu conexión.\n"
        "¿Qué internet usas ahora?",
        "NexgloTV needs a stable internet connection. QCell is a local option.\n"
        "Around **3 Mbps** may suit basic lower-quality streaming, but HD quality depends on your connection.\n"
        "What internet are you using now?",
    ),
    "mbps_clarification": (
        "Nota: **3 Mbps** (megabits por segundo) no es lo mismo que **3 MB/s** (megabytes por segundo).\n"
        "1 MB/s = 8 Mbps. Para HD se recomienda 5+ Mbps sostenidos.",
        "Note: **3 Mbps** (megabits per second) is not the same as **3 MB/s** (megabytes per second).\n"
        "1 MB/s = 8 Mbps. For HD, 5+ Mbps sustained is recommended.",
    ),

    # ---------------------------------------------------------- non-smart TV
    "firestick_suggestion": (
        "Un Fire TV Stick compatible puede permitir streaming en un TV con HDMI.\n"
        "Puedo ayudarte a revisar tu modelo de TV; nuestro equipo también puede confirmar vendedores y precios locales actuales.",
        "A compatible Fire TV Stick may enable streaming on a TV with HDMI.\n"
        "I can help check your TV model; our team can also confirm current local sellers and prices.",
    ),

    # ----------------------------------------------------------- referrals
    "referral_prompt": (
        "¡Gracias por recomendar NexgloTV! 😊\nCuéntame el código o nombre de quien te refirió y lo anotamos para que ambos reciban el beneficio cuando se verifique el pago.",
        "Thanks for referring NexgloTV! 😊\nTell me the referral code or name and we'll log it so both of you get the benefit once payment is verified.",
    ),

    # ----------------------------------------------------------- DStv comparison
    "dstv_comparison": (
        "NexgloTV es un servicio de televisión por internet, no satélite. No requiere antena parabólica.\n"
        "Ofrecemos muchos canales de deportes, noticias, películas y series, pero **no garantizamos todos los canales de DStv/SuperSport** ni ligas específicas 24/7.\n"
        "Dime qué canal o liga te interesa y verifico su disponibilidad actual.",
        "NexgloTV is an internet TV service, not satellite. No satellite dish needed.\n"
        "We offer many sports, news, movie and series channels, but **don't guarantee all DStv/SuperSport channels** or specific leagues 24/7.\n"
        "Tell me what channel or league you want and I'll check current availability.",
    ),

    # ----------------------------------------------------------- automations
    "auto_followup_quote": (
        "¡Hola! 👋 Solo paso a revisar si tienes alguna duda sobre los paquetes de **NexgloTV** o la instalación.\n"
        "Recuerda que configuramos tu dispositivo primero y pagas solo después de ver que funciona. Responde cuando quieras continuar.",
        "Hi there! 👋 Just checking in to see if you have any questions about **NexgloTV** packages or setup.\n"
        "Remember, we set up your device first and you only pay after you confirm it works. Reply whenever you're ready to continue!",
    ),
    "auto_trial_expired": (
        "⏰ Tu prueba gratis de **NexgloTV** ha finalizado.\n"
        "¿Te gustó el servicio? Si deseas activar tu suscripción completa ahora, responde con el paquete que prefieras (por ejemplo *1 mes 1 dispositivo*) y lo dejamos activo enseguida.",
        "⏰ Your **NexgloTV** free trial has ended.\n"
        "How did you like the service? If you'd like to activate your full subscription now, reply with your preferred package (e.g. *1 month 1 device*) and we'll get you set up right away.",
    ),
    "auto_payment_reminder": (
        "Hola 👋, tu configuración de **NexgloTV** ya está verificada y lista.\n"
        "Para mantener tu cuenta activa, envíanos una foto o captura de tu comprobante de pago por aquí cuando lo tengas listo.",
        "Hi there 👋, your **NexgloTV** setup is verified and ready.\n"
        "To keep your account active, please send a photo or screenshot of your payment receipt here whenever you're ready.",
    ),
    "auto_renewal_reminder": (
        "🔔 Hola 👋, tu suscripción de **NexgloTV** ({package}) vence pronto ({expires}).\n"
        "¿Deseas renovar ahora para seguir disfrutando sin interrupciones? Responde *renovar* para continuar.",
        "🔔 Hi there 👋, your **NexgloTV** subscription ({package}) expires soon ({expires}).\n"
        "Would you like to renew now for uninterrupted viewing? Reply *renew* to continue.",
    ),
}


def t(key: str, lang: str, **kwargs) -> str:
    """Render a bilingual string with formatting."""
    es, en = STRINGS[key]
    template = en if lang == "en" else es
    return template.format(**kwargs) if kwargs else template


def pluralize(count: int, lang: str) -> str:
    """Return 's' for plural in English, 'es'/'s' in Spanish as appropriate."""
    if count == 1:
        return ""
    return "es" if lang == "es" else "s"
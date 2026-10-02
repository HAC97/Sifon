from enum import Enum


class ErrorCode(str, Enum):
    INVALID_URL = "INVALID_URL"
    UNSUPPORTED_SITE = "UNSUPPORTED_SITE"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    GEO_BLOCKED = "GEO_BLOCKED"
    FFMPEG_MISSING = "FFMPEG_MISSING"
    NETWORK = "NETWORK"
    BLOCKED_ADDRESS = "BLOCKED_ADDRESS"
    TOO_LARGE = "TOO_LARGE"
    TOO_LONG = "TOO_LONG"
    QUEUE_FULL = "QUEUE_FULL"
    DISK_FULL = "DISK_FULL"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


USER_MESSAGES = {
    ErrorCode.INVALID_URL: "La URL no es válida. Pegá un enlace completo que empiece con http:// o https://.",
    ErrorCode.UNSUPPORTED_SITE: "Este sitio o enlace no está soportado.",
    ErrorCode.LOGIN_REQUIRED: "El video es privado o requiere iniciar sesión, y esta app no soporta login.",
    ErrorCode.GEO_BLOCKED: "El video no está disponible en tu país.",
    ErrorCode.FFMPEG_MISSING: "No se encontró ffmpeg. Instalalo y reiniciá la app.",
    ErrorCode.NETWORK: "Falló la conexión con el sitio. Revisá tu internet y probá de nuevo.",
    ErrorCode.BLOCKED_ADDRESS: "El enlace, o una redirección, apunta a una red local o reservada y está bloqueado.",
    ErrorCode.TOO_LARGE: "El archivo supera el tamaño máximo permitido (SIFON_MAX_FILESIZE_MB).",
    ErrorCode.TOO_LONG: "El video supera la duración máxima permitida (SIFON_MAX_DURATION_MIN) o es una transmisión en vivo.",
    ErrorCode.QUEUE_FULL: "Hay demasiadas descargas en curso o en cola. Esperá a que termine alguna.",
    ErrorCode.DISK_FULL: "No hay espacio libre suficiente en el disco (SIFON_MIN_FREE_DISK_MB).",
    ErrorCode.CANCELLED: "La descarga se canceló.",
    ErrorCode.UNKNOWN: "No se pudo descargar el video. Probá de nuevo o actualizá yt-dlp.",
}


class DownloadFailure(Exception):
    def __init__(self, code: ErrorCode, message: str | None = None):
        self.code = code
        self.message = message or USER_MESSAGES[code]
        super().__init__(self.message)


# First match wins, so the specific causes come before the generic NETWORK words.
_RULES = [
    # Marker written by app.egress_proxy in the reason phrase of its refusals.
    (ErrorCode.BLOCKED_ADDRESS, ("sifon-blocked-address",)),
    (
        ErrorCode.FFMPEG_MISSING,
        ("ffmpeg not found", "ffprobe not found", "ffprobe and ffmpeg not found", "ffmpeg is not installed"),
    ),
    (ErrorCode.UNSUPPORTED_SITE, ("unsupported url",)),
    (
        ErrorCode.LOGIN_REQUIRED,
        ("sign in", "log in", "login", "private video", "members-only", "confirm your age", "age-restricted"),
    ),
    (
        ErrorCode.GEO_BLOCKED,
        ("not available in your country", "blocked it in your country", "geo restriction", "geo-restricted"),
    ),
    # After login and geo (their messages can also say "unavailable"), before NETWORK
    # (yt-dlp words a 404 as "Unable to download webpage: HTTP Error 404").
    (
        ErrorCode.UNSUPPORTED_SITE,
        ("http error 404", "http error 410", "video unavailable", "this video is unavailable", "not found"),
    ),
    (
        ErrorCode.NETWORK,
        (
            "timed out",
            "connection",
            "name or service not known",
            "getaddrinfo",
            "http error 5",
            "unable to download",
            "temporary failure in name resolution",
        ),
    ),
]


def map_error(message: str) -> ErrorCode:
    text = message.lower()
    for code, needles in _RULES:
        if any(needle in text for needle in needles):
            return code
    return ErrorCode.UNKNOWN


# HTTP status of a DownloadFailure raised before a job exists. Everything else is a plain 400.
HTTP_STATUS = {
    ErrorCode.QUEUE_FULL: 429,
    ErrorCode.DISK_FULL: 507,
}

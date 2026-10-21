"""Storages de estaticos para produccion: nombres con hash (ideas.3f2a9c.css).

Los CSS de librerias de terceros (bootstrap, font-awesome...) traen
referencias a archivos que no vienen en el repo, como su sourcemap
(`/*# sourceMappingURL=bootstrap.min.css.map */`). El storage con manifest
de Django falla en `collectstatic` al no encontrarlos. Estas variantes
dejan esas referencias tal cual (igual que sin manifest) y hashean todo
lo demas.
"""

from django.contrib.staticfiles.storage import ManifestStaticFilesStorage


class _ToleraReferenciasFaltantes:
    def hashed_name(self, name, content=None, filename=None):
        try:
            return super().hashed_name(name, content, filename)
        except ValueError:
            # Archivo referenciado desde un CSS que no existe: se deja el
            # nombre original. Solo pasa con `content` vacio (referencias);
            # un archivo propio que falta en el manifest sigue fallando en
            # `stored_name` (manifest_strict).
            if content is not None:
                raise
            return name


class ManifestTolerante(_ToleraReferenciasFaltantes, ManifestStaticFilesStorage):
    """Para cuando nginx sirve /static/ (USE_WHITENOISE=False)."""


try:
    from whitenoise.storage import CompressedManifestStaticFilesStorage
except ImportError:  # pragma: no cover - whitenoise es opcional en dev
    CompressedManifestStaticFilesStorage = None
else:
    class CompressedManifestTolerante(
        _ToleraReferenciasFaltantes, CompressedManifestStaticFilesStorage,
    ):
        """Igual, mas los .gz/.br que sirve WhiteNoise (o gzip_static)."""

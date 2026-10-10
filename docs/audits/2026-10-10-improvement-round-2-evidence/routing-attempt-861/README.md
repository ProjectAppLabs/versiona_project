# Intento de navegador interrumpido y diagnóstico de rutas

El primer E2E sobre 8611077 se interrumpió tras errores de página Next 404; no constituye un resultado verde ni un manifiesto completo. Los contexts originales y la caché se conservan en el scratch privado. Aquí se archivan sus hashes y el diagnóstico HTTP/DOM saneado. La ejecución final procede de e2e-clean-cache-retry, separada y con cero retries de Playwright. No se modificó aplicación, tests, dependencias ni configuración para recuperar la ruta; sólo se preservó la caché del servidor privado y se reinició el mismo comando.

# Evidencia de revisión — Versiona, ronda 3

Source probado: `a34d14c1012387c676da45b9d68ce451dcff78c4`; tree `187fd6a5d39116deb1cef110ab632363188c7597`.

- `qa-manifest-original.json`: copia byte a byte del manifest canónico aprobado; referencias a artefactos privados válidas durante la verificación.
- `validation-summary.json`: conteos derivados, comandos literales, exits, guardas y hashes de los doce artefactos originales. No es una ejecución adicional.
- `quality-gates-summary.json`: resúmenes derivados de los tres JSON estrictos, con advertencias, excepciones heredadas y resultados de lint real conservados.
- `source-provenance.json`: propiedad exclusiva de quince archivos del source probado. Los metadatos posteriores pertenecen sólo a compartido.
- `canonical-ledger-verification.json`: prueba derivada de record-qa/validate-qa y los tres IDs verified; no certifica otros scopes.
- `validation-history.json`: rechazos y fallos de preparación preservados; C2 histórico de causa incierta.

123/123 casos finales: backend 36, unitarios 62 y E2E 25. Cero skips/flaky/retries. Wrapper oficial exit 1/WARN heredado; gate estricto cero errores/infra.

Los originales con logs, JUnit, JSON, traces y cachés se conservan privadamente en `/tmp/versiona-improvement-10102026-ronda3/final-qa-originals-a34d14c/`, con hashes y sin seguir symlinks. Ese archivo no se versiona ni se expone. No se publican estados autenticados, URLs firmadas, credenciales, traces ni cachés.

Los reportes de CI del tren y los PR acreditan los heads finales; no se atribuyen metadatos añadidos después a este SHA. Esta carpeta es evidencia saneada para revisión, no sustituto de los originales que comprobó el motor.

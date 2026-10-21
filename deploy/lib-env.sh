# Funciones compartidas por los scripts de deploy. Se carga con:
#   source "$(dirname "$0")/lib-env.sh"

# cargar_env <archivo>
#
# Lee un .env (CLAVE=valor por linea) y exporta cada variable SIN
# interpretar el valor como bash, igual que hace django-environ.
#
# Antes los scripts hacian `set -a; source .env`, y un valor valido para
# Django como `DEFAULT_FROM_EMAIL=Ideas Boutique <ventas@ideasboutique.cl>`
# rompia el script: bash toma `<` y `>` como redirecciones ("syntax error
# near unexpected token `newline'"), y el backup diario fallaba.
#
# Soporta: lineas vacias y comentarios (#), prefijo `export`, valores
# entre comillas simples o dobles (se quitan), comentario al final de un
# valor sin comillas (` # ...`) y fin de linea CRLF.
cargar_env() {
  local archivo="$1" linea clave valor
  while IFS= read -r linea || [[ -n "$linea" ]]; do
    linea="${linea%$'\r'}"
    [[ "$linea" =~ ^[[:space:]]*(#|$) ]] && continue
    [[ "$linea" == *=* ]] || continue
    clave="${linea%%=*}"
    clave="${clave#"${clave%%[![:space:]]*}"}"
    clave="${clave#export }"
    clave="${clave//[[:space:]]/}"
    [[ "$clave" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    valor="${linea#*=}"
    if [[ "$valor" =~ ^[[:space:]]*\"(.*)\"[[:space:]]*$ ]] \
        || [[ "$valor" =~ ^[[:space:]]*\'(.*)\'[[:space:]]*$ ]]; then
      valor="${BASH_REMATCH[1]}"
    else
      valor="$(sed -E 's/[[:space:]]+#.*$//; s/^[[:space:]]+//; s/[[:space:]]+$//' <<<"$valor")"
    fi
    export "$clave=$valor"
  done < "$archivo"
}

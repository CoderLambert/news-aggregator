#!/bin/sh
set -eu

read_secret() {
  secret_path="$1"
  if [ ! -r "$secret_path" ]; then
    printf '%s\n' 'required runtime secret is unreadable' >&2
    exit 64
  fi
  cat "$secret_path"
}

postgres_password="$(read_secret /run/secrets/postgres_password)"
master_key="$(read_secret /run/secrets/litellm_master_key)"
salt_key="$(read_secret /run/secrets/litellm_salt_key)"

case "$postgres_password" in
  ''|*[!0123456789abcdefABCDEF]*)
    printf '%s\n' 'database password must be a non-empty hexadecimal value' >&2
    exit 64
    ;;
esac
if [ "${#postgres_password}" -lt 32 ]; then
  printf '%s\n' 'database password is shorter than the required minimum' >&2
  exit 64
fi

case "$master_key" in
  sk-*) ;;
  *)
    printf '%s\n' 'LiteLLM master key has an invalid format' >&2
    exit 64
    ;;
esac
if [ "${#master_key}" -lt 40 ]; then
  printf '%s\n' 'LiteLLM master key is shorter than the required minimum' >&2
  exit 64
fi
if [ "${#salt_key}" -lt 32 ]; then
  printf '%s\n' 'LiteLLM salt key is shorter than the required minimum' >&2
  exit 64
fi

export LITELLM_MASTER_KEY="$master_key"
export LITELLM_SALT_KEY="$salt_key"
export DATABASE_URL="postgresql://${POSTGRES_USER}:${postgres_password}@${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}"
unset postgres_password master_key salt_key

exec litellm "$@"

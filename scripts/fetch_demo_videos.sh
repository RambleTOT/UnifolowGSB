#!/usr/bin/env bash
# Скачать демонстрационные ролики в data/videos.
#
# Ролики открытые, из набора примеров Intel (репозиторий intel-iot-devkit/
# sample-videos, лицензия Apache 2.0). Рядом с каждым уже лежит разметка
# <имя>.markup.json — она в репозитории, поэтому первый старт после скачивания
# сразу даёт четыре считающих источника.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="${UNIFLOW_VIDEO_DIR:-$ROOT_DIR/data/videos}"
BASE_URL="https://raw.githubusercontent.com/intel-iot-devkit/sample-videos/master"

# Ролик : источник, которому он достанется (имя записано в самой разметке)
FILES=(
  "people-detection.mp4"            # Столовая
  "store-aisle-detection.mp4"       # Раздача
  "one-by-one-person-detection.mp4" # КПП 1
)
# КПП 2 — прямой эфир с камеры, его описание в palace-square.stream.json.

mkdir -p "$TARGET_DIR"
for name in "${FILES[@]}"; do
  target="$TARGET_DIR/$name"
  if [ -s "$target" ]; then
    echo "уже есть: $name"
    continue
  fi
  echo "скачиваю: $name"
  curl -fsSL --retry 2 -o "$target.part" "$BASE_URL/$name"
  mv "$target.part" "$target"
  echo "  готово, $(du -h "$target" | cut -f1)"
done

missing=0
for name in "${FILES[@]}"; do
  markup="$TARGET_DIR/${name%.mp4}.markup.json"
  [ -f "$markup" ] || { echo "нет разметки: $(basename "$markup")"; missing=1; }
done
if [ "$missing" = 1 ]; then
  echo "Без разметки видео не попадёт ни к одному источнику — проверьте каталог."
  exit 1
fi

echo
echo "Готово. Файлы в $TARGET_DIR."
echo "Первый запуск на чистой базе разберёт их по источникам сам."

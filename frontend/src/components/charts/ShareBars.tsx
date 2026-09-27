import { formatNumber } from "../../lib/format";

interface ShareBarsProps {
  items: Array<{ id: string | number; name: string; note?: string; value: number; share?: number }>;
  unit?: string;
  onSelect?: (id: string | number) => void;
}

/**
 * Сравнение по долям. Выбрана горизонтальная шкала, потому что названия
 * источников длинные и в столбчатой диаграмме не читаются.
 */
export function ShareBars({ items, unit = "", onSelect }: ShareBarsProps) {
  const max = Math.max(1, ...items.map((item) => item.value));

  return (
    <ul className="share-bars">
      {items.map((item) => (
        <li key={item.id} className="share-bars__row">
          <button
            type="button"
            className="share-bars__label"
            onClick={() => onSelect?.(item.id)}
            disabled={!onSelect}
          >
            <span>{item.name}</span>
            {item.note && <small>{item.note}</small>}
          </button>
          <div className="share-bars__track">
            <div
              className="share-bars__fill"
              style={{ width: `${Math.max(2, (item.value / max) * 100)}%` }}
            />
          </div>
          <span className="share-bars__value tabular">
            {formatNumber(item.value)} {unit}
            {item.share !== undefined && <small> · {item.share} %</small>}
          </span>
        </li>
      ))}
    </ul>
  );
}

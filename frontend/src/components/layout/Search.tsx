import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { useSearch } from "../../api/queries";
import { label } from "../../lib/dictionary";
import { formatFreshness } from "../../lib/format";

interface Item {
  key: string;
  group: string;
  title: string;
  note: string;
  to: string;
}

/**
 * Поиск по источникам, событиям и разделам (ТЗ, раздел 4.3).
 *
 * Результаты сгруппированы, выбор возможен с клавиатуры: стрелки ведут по
 * списку, Enter открывает, Esc закрывает.
 */
export function Search() {
  const [value, setValue] = useState("");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [debounced, setDebounced] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);
  const navigate = useNavigate();

  useEffect(() => {
    const timer = window.setTimeout(() => setDebounced(value), 220);
    return () => window.clearTimeout(timer);
  }, [value]);

  const results = useSearch(debounced);

  const items = useMemo<Item[]>(() => {
    const data = results.data;
    if (!data) return [];
    return [
      ...data.sources.map((source) => ({
        key: `source-${source.id}`,
        group: "Источники",
        title: source.name,
        note: `${label("scope", source.scope)} · ${label("readiness", source.readiness)}`,
        to: source.to,
      })),
      ...data.events.map((event) => ({
        key: `event-${event.id}`,
        group: "События",
        title: event.title,
        note: `${label("severity", event.severity)} · ${formatFreshness(event.startedAt)}`,
        to: event.to,
      })),
      ...data.sections.map((section) => ({
        key: `section-${section.to}`,
        group: "Разделы",
        title: section.title,
        note: "раздел интерфейса",
        to: section.to,
      })),
    ];
  }, [results.data]);

  useEffect(() => setActive(0), [items.length]);

  useEffect(() => {
    const onClickOutside = (event: MouseEvent) => {
      if (!containerRef.current?.contains(event.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  const go = (item: Item) => {
    setOpen(false);
    setValue("");
    navigate(item.to);
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key === "Escape") {
      setOpen(false);
      return;
    }
    if (!items.length) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      setActive((index) => (index + 1) % items.length);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      setActive((index) => (index - 1 + items.length) % items.length);
    } else if (event.key === "Enter") {
      event.preventDefault();
      go(items[active]);
    }
  };

  let lastGroup = "";

  return (
    <div className="search" ref={containerRef}>
      <input
        className="search__input"
        placeholder="Поиск: источник, событие, раздел"
        value={value}
        onChange={(event) => {
          setValue(event.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
        aria-label="Поиск по источникам, событиям и разделам"
        aria-expanded={open}
      />

      {open && debounced.trim().length >= 2 && (
        <div className="search__results" role="listbox">
          {results.isFetching && items.length === 0 && <p className="muted">Ищем…</p>}

          {!results.isFetching && items.length === 0 && (
            <p className="muted">
              Ничего не найдено. Попробуйте название источника, слово из события или название
              раздела.
            </p>
          )}

          {items.map((item, index) => {
            const header = item.group !== lastGroup ? item.group : null;
            lastGroup = item.group;
            return (
              <div key={item.key}>
                {header && <div className="search__group">{header}</div>}
                <button
                  type="button"
                  role="option"
                  aria-selected={index === active}
                  className={`search__item ${index === active ? "search__item--active" : ""}`}
                  onMouseEnter={() => setActive(index)}
                  onClick={() => go(item)}
                >
                  <span className="search__title">{item.title}</span>
                  <small>{item.note}</small>
                </button>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

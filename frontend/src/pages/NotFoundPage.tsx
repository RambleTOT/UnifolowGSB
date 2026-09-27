import { Link } from "react-router-dom";

import { Panel } from "../components/common/Panel";

export function NotFoundPage() {
  return (
    <div className="page">
      <h1 className="page__title">Раздел не найден</h1>
      <Panel>
        <div className="empty">
          <div className="empty__title">Такой страницы нет</div>
          <p className="empty__text">Проверьте адрес или вернитесь на главную.</p>
          <div className="empty__action">
            <Link to="/">На главную</Link>
          </div>
        </div>
      </Panel>
    </div>
  );
}

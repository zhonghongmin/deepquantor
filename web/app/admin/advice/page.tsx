import { AdminShell } from "../components/AdminShell";
import { PageBody } from "../components/PageBody";

/** 投资建议（对内版）（`#advice` · AD-08） */
export default function Page() {
  return (
    <AdminShell active="advice">
      <section id="advice">
        <PageBody pageId="advice" />
      </section>
    </AdminShell>
  );
}

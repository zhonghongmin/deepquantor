import { AdminShell } from "../components/AdminShell";
import { PageBody } from "../components/PageBody";

/** 运营看板（`#ops` · AD-06） */
export default function Page() {
  return (
    <AdminShell active="ops">
      <section id="ops">
        <PageBody pageId="ops" />
      </section>
    </AdminShell>
  );
}

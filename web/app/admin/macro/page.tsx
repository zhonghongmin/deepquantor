import { AdminShell } from "../components/AdminShell";
import { PageBody } from "../components/PageBody";

/** 宏观数据（`#macro` · AD-10） */
export default function Page() {
  return (
    <AdminShell active="macro">
      <section id="macro">
        <PageBody pageId="macro" />
      </section>
    </AdminShell>
  );
}

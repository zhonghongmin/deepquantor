import { AdminShell } from "../components/AdminShell";
import { PageBody } from "../components/PageBody";

/** 微观数据（`#micro` · AD-12） */
export default function Page() {
  return (
    <AdminShell active="micro">
      <section id="micro">
        <PageBody pageId="micro" />
      </section>
    </AdminShell>
  );
}

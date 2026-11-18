import { AdminShell } from "../components/AdminShell";
import { PageBody } from "../components/PageBody";

/** 权限与审计（`#audit` · AD-07） */
export default function Page() {
  return (
    <AdminShell active="audit">
      <section id="audit">
        <PageBody pageId="audit" />
      </section>
    </AdminShell>
  );
}

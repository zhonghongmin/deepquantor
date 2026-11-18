import { AdminShell } from "../components/AdminShell";
import { PageBody } from "../components/PageBody";

/** 投研与回测（`#research` · AD-04） */
export default function Page() {
  return (
    <AdminShell active="research">
      <section id="research">
        <PageBody pageId="research" />
      </section>
    </AdminShell>
  );
}

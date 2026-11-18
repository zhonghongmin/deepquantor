import { AdminShell } from "../components/AdminShell";
import { PageBody } from "../components/PageBody";

/** 用户管理（`#users` · AD-01） */
export default function Page() {
  return (
    <AdminShell active="users">
      <section id="users">
        <PageBody pageId="users" />
      </section>
    </AdminShell>
  );
}

"use server";
import { revalidatePath } from "next/cache";
import { redirect } from "next/navigation";
import { createServerClient } from "@/lib/supabase/server";
import { z } from "zod";
import AutoGPTServerAPI from "@/lib/autogpt-server-api";
import AutoGPTServerAPIServerSide from "@/lib/autogpt-server-api/clientServer";

const loginFormSchema = z.object({
  email: z.string().email().min(2).max(64),
  password: z.string().min(6).max(64),
});

export async function login(values: z.infer<typeof loginFormSchema>) {
  const supabase = createServerClient();

  if (!supabase) {
    redirect("/error");
  }

  // We are sure that the values are of the correct type because zod validates the form
  const { data, error } = await supabase.auth.signInWithPassword(values);

  if (error) {
    return error.message;
  }

  if (data.session) {
    await supabase.auth.setSession(data.session);
  }

  revalidatePath("/", "layout");
  redirect("/profile");
}

export async function signup(values: z.infer<typeof loginFormSchema>) {
  "use server";
  const supabase = createServerClient();

  if (!supabase) {
    redirect("/error");
  }

  // We are sure that the values are of the correct type because zod validates the form
  const { data, error } = await supabase.auth.signUp(values);

  if (error) {
    return error.message;
  }

  if (data.session) {
    await supabase.auth.setSession(data.session);
  }
  if (data.user) {
    // This wll throw an error until the user is created in the database, this should be resolved
    // when we merge supabase and the postgres database. Follow up on 14Oct2024.
    const api = new AutoGPTServerAPIServerSide();

    api.logCreateUser({
      email: values.email,
      user_id: data.user.id,
      name: values.email,
      username: values.email,
    });
  }

  revalidatePath("/", "layout");
  redirect("/profile");
}

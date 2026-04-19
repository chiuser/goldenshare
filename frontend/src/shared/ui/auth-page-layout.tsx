import { Paper, Stack, Text, Title } from "@mantine/core";
import type { ReactNode } from "react";


interface AuthPageLayoutProps {
  kicker: string;
  title: string;
  description: string;
  children: ReactNode;
  hero?: ReactNode;
  maxWidth?: number;
}

export function AuthPageLayout({
  kicker,
  title,
  description,
  children,
  hero,
  maxWidth = 500,
}: AuthPageLayoutProps) {
  return (
    <div className="app-gradient-shell app-centered-shell">
      <Paper className="glass-card auth-page-layout" radius="md" p={36} miw={360} maw={maxWidth} w="100%">
        <Stack gap="lg">
          {hero ? (
            <Stack gap="md" align="center">
              {hero}
            </Stack>
          ) : null}

          <Stack gap={6}>
            <Text className="auth-page-layout__kicker" fw={600} size="xs">
              {kicker}
            </Text>
            <Title className="auth-page-layout__title" order={1}>
              {title}
            </Title>
            <Text className="auth-page-layout__description" size="sm">
              {description}
            </Text>
          </Stack>

          {children}
        </Stack>
      </Paper>
    </div>
  );
}

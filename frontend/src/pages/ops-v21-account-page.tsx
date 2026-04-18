import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Checkbox,
  Group,
  NumberInput,
  Paper,
  Stack,
  Table,
  Tabs,
  Text,
  TextInput,
  Tooltip,
} from "@mantine/core";
import { IconCopy } from "@tabler/icons-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { apiRequest } from "../shared/api/client";
import type {
  AdminInviteCreateResponse,
  AdminInviteListResponse,
  AdminUserListItem,
  AdminUserListResponse,
} from "../shared/api/types";
import { formatDateTimeLabel } from "../shared/date-format";
import { SectionCard } from "../shared/ui/section-card";


const ROLE_OPTIONS = ["admin", "operator", "analyst", "viewer"] as const;
const ACCOUNT_STATE_OPTIONS = ["active", "suspended", "locked", "pending_verification"] as const;

type RoleKey = typeof ROLE_OPTIONS[number];

interface CreateUserDraft {
  username: string;
  password: string;
  displayName: string;
  email: string;
  isAdmin: boolean;
  isActive: boolean;
  accountState: string;
  roles: RoleKey[];
}

interface EditUserDraft {
  userId: number;
  username: string;
  displayName: string;
  email: string;
  isAdmin: boolean;
  isActive: boolean;
  accountState: string;
  roles: RoleKey[];
}

function emptyCreateDraft(): CreateUserDraft {
  return {
    username: "",
    password: "",
    displayName: "",
    email: "",
    isAdmin: false,
    isActive: true,
    accountState: "active",
    roles: ["viewer"],
  };
}

function toEditDraft(item: AdminUserListItem): EditUserDraft {
  const roles = (item.roles.filter((role): role is RoleKey => ROLE_OPTIONS.includes(role as RoleKey)) || []) as RoleKey[];
  return {
    userId: item.id,
    username: item.username,
    displayName: item.display_name || "",
    email: item.email || "",
    isAdmin: item.is_admin,
    isActive: item.is_active,
    accountState: item.account_state,
    roles: roles.length > 0 ? roles : [item.is_admin ? "admin" : "viewer"],
  };
}

function normalizeRoles(roles: RoleKey[], isAdmin: boolean): RoleKey[] {
  const set = new Set<RoleKey>(roles);
  if (isAdmin) set.add("admin");
  if (set.size === 0) set.add(isAdmin ? "admin" : "viewer");
  return Array.from(set.values());
}

export function OpsV21AccountPage() {
  const queryClient = useQueryClient();
  const [keyword, setKeyword] = useState("");
  const [createDraft, setCreateDraft] = useState<CreateUserDraft>(emptyCreateDraft());
  const [editingUser, setEditingUser] = useState<EditUserDraft | null>(null);
  const [resetTarget, setResetTarget] = useState<AdminUserListItem | null>(null);
  const [resetPassword, setResetPassword] = useState("");
  const [actionError, setActionError] = useState<string | null>(null);
  const [inviteRole, setInviteRole] = useState<RoleKey>("viewer");
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteMaxUses, setInviteMaxUses] = useState(1);
  const [inviteNote, setInviteNote] = useState("");
  const [inviteCode, setInviteCode] = useState("");
  const [createdInviteCode, setCreatedInviteCode] = useState<string | null>(null);

  const userQueryString = (() => {
    const params = new URLSearchParams();
    params.set("limit", "200");
    params.set("offset", "0");
    if (keyword.trim()) params.set("keyword", keyword.trim());
    return params.toString();
  })();

  const usersQuery = useQuery({
    queryKey: ["admin", "users", userQueryString],
    queryFn: () => apiRequest<AdminUserListResponse>(`/api/v1/admin/users?${userQueryString}`),
  });

  const invitesQuery = useQuery({
    queryKey: ["admin", "invites"],
    queryFn: () => apiRequest<AdminInviteListResponse>("/api/v1/admin/invites?include_disabled=true&limit=200&offset=0"),
  });

  const createUserMutation = useMutation({
    mutationFn: () =>
      apiRequest<AdminUserListItem>("/api/v1/admin/users", {
        method: "POST",
        body: {
          username: createDraft.username,
          password: createDraft.password,
          display_name: createDraft.displayName || null,
          email: createDraft.email || null,
          is_admin: createDraft.isAdmin,
          is_active: createDraft.isActive,
          account_state: createDraft.accountState,
          roles: normalizeRoles(createDraft.roles, createDraft.isAdmin),
        },
      }),
    onSuccess: () => {
      setActionError(null);
      setCreateDraft(emptyCreateDraft());
      void queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
    },
    onError: (error) => {
      setActionError(error instanceof Error ? error.message : "创建账号失败");
    },
  });

  const updateUserMutation = useMutation({
    mutationFn: (draft: EditUserDraft) =>
      apiRequest<AdminUserListItem>(`/api/v1/admin/users/${draft.userId}`, {
        method: "PATCH",
        body: {
          display_name: draft.displayName || null,
          email: draft.email || null,
          is_admin: draft.isAdmin,
          is_active: draft.isActive,
          account_state: draft.accountState,
        },
      }),
    onSuccess: () => {
      setActionError(null);
      void queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
    },
    onError: (error) => {
      setActionError(error instanceof Error ? error.message : "更新账号失败");
    },
  });

  const updateRolesMutation = useMutation({
    mutationFn: (draft: EditUserDraft) =>
      apiRequest<AdminUserListItem>(`/api/v1/admin/users/${draft.userId}/roles`, {
        method: "POST",
        body: { roles: normalizeRoles(draft.roles, draft.isAdmin) },
      }),
    onSuccess: () => {
      setActionError(null);
      void queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
    },
    onError: (error) => {
      setActionError(error instanceof Error ? error.message : "更新角色失败");
    },
  });

  const suspendOrActivateMutation = useMutation({
    mutationFn: (item: AdminUserListItem) =>
      apiRequest<AdminUserListItem>(`/api/v1/admin/users/${item.id}/${item.is_active ? "suspend" : "activate"}`, {
        method: "POST",
      }),
    onSuccess: () => {
      setActionError(null);
      void queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
    },
    onError: (error) => {
      setActionError(error instanceof Error ? error.message : "状态切换失败");
    },
  });

  const deleteUserMutation = useMutation({
    mutationFn: (item: AdminUserListItem) =>
      apiRequest<void>(`/api/v1/admin/users/${item.id}`, { method: "DELETE" }),
    onSuccess: () => {
      setActionError(null);
      setEditingUser(null);
      void queryClient.invalidateQueries({ queryKey: ["admin", "users"] });
    },
    onError: (error) => {
      setActionError(error instanceof Error ? error.message : "删除账号失败");
    },
  });

  const resetPasswordMutation = useMutation({
    mutationFn: () =>
      apiRequest<void>(`/api/v1/admin/users/${resetTarget?.id}/reset-password`, {
        method: "POST",
        body: { password: resetPassword },
      }),
    onSuccess: () => {
      setActionError(null);
      setResetTarget(null);
      setResetPassword("");
    },
    onError: (error) => {
      setActionError(error instanceof Error ? error.message : "重置密码失败");
    },
  });

  const createInviteMutation = useMutation({
    mutationFn: () =>
      apiRequest<AdminInviteCreateResponse>("/api/v1/admin/invites", {
        method: "POST",
        body: {
          role_key: inviteRole,
          assigned_email: inviteEmail || null,
          max_uses: inviteMaxUses,
          note: inviteNote || null,
          code: inviteCode || null,
        },
      }),
    onSuccess: (payload) => {
      setActionError(null);
      setCreatedInviteCode(payload.code);
      setInviteEmail("");
      setInviteMaxUses(1);
      setInviteNote("");
      setInviteCode("");
      void queryClient.invalidateQueries({ queryKey: ["admin", "invites"] });
    },
    onError: (error) => {
      setActionError(error instanceof Error ? error.message : "创建邀请码失败");
    },
  });

  const disableInviteMutation = useMutation({
    mutationFn: (inviteId: number) =>
      apiRequest<void>(`/api/v1/admin/invites/${inviteId}`, { method: "DELETE" }),
    onSuccess: () => {
      setActionError(null);
      void queryClient.invalidateQueries({ queryKey: ["admin", "invites"] });
    },
    onError: (error) => {
      setActionError(error instanceof Error ? error.message : "停用邀请码失败");
    },
  });

  const deleteInviteMutation = useMutation({
    mutationFn: (inviteId: number) =>
      apiRequest<void>(`/api/v1/admin/invites/${inviteId}/hard-delete`, { method: "DELETE" }),
    onSuccess: () => {
      setActionError(null);
      void queryClient.invalidateQueries({ queryKey: ["admin", "invites"] });
    },
    onError: (error) => {
      setActionError(error instanceof Error ? error.message : "删除邀请码失败");
    },
  });

  const copyInviteCode = async (code: string) => {
    if (!code.trim()) return;
    try {
      await navigator.clipboard.writeText(code);
      setActionError(null);
    } catch {
      setActionError("复制失败，请手动复制邀请码");
    }
  };

  return (
    <Stack gap="lg">
      <SectionCard title="帐号管理" description="管理员统一管理账号与邀请码。">
        {actionError ? (
          <Alert color="red" title="操作失败">
            {actionError}
          </Alert>
        ) : null}
        {createdInviteCode ? (
          <Alert color="blue" title="邀请码已创建">
            当前邀请码：<Text span fw={700}>{createdInviteCode}</Text>
          </Alert>
        ) : null}
        <Tabs defaultValue="users">
          <Tabs.List>
            <Tabs.Tab value="users">用户管理</Tabs.Tab>
            <Tabs.Tab value="invites">邀请码</Tabs.Tab>
          </Tabs.List>

          <Tabs.Panel value="users" pt="md">
            <Stack gap="md">
              <Paper p="md" radius="md" withBorder>
                <Stack gap="sm">
                  <Group grow align="end">
                    <TextInput
                      label="搜索用户"
                      placeholder="用户名 / 显示名 / 邮箱"
                      value={keyword}
                      onChange={(event) => setKeyword(event.currentTarget.value)}
                    />
                    <Button variant="light" onClick={() => void usersQuery.refetch()}>
                      刷新列表
                    </Button>
                  </Group>
                  <Text size="xs" c="dimmed">共 {usersQuery.data?.total ?? 0} 个账号</Text>
                </Stack>
              </Paper>

              <Paper p="md" radius="md" withBorder>
                <Stack gap="sm">
                  <Text fw={700}>新建账号</Text>
                  <Group grow>
                    <TextInput
                      label="用户名"
                      value={createDraft.username}
                      onChange={(event) => {
                        const value = event.currentTarget.value;
                        setCreateDraft((prev) => ({ ...prev, username: value }));
                      }}
                    />
                    <TextInput
                      label="初始密码"
                      value={createDraft.password}
                      onChange={(event) => {
                        const value = event.currentTarget.value;
                        setCreateDraft((prev) => ({ ...prev, password: value }));
                      }}
                    />
                  </Group>
                  <Group grow>
                    <TextInput
                      label="显示名称"
                      value={createDraft.displayName}
                      onChange={(event) => {
                        const value = event.currentTarget.value;
                        setCreateDraft((prev) => ({ ...prev, displayName: value }));
                      }}
                    />
                    <TextInput
                      label="邮箱"
                      value={createDraft.email}
                      onChange={(event) => {
                        const value = event.currentTarget.value;
                        setCreateDraft((prev) => ({ ...prev, email: value }));
                      }}
                    />
                  </Group>
                  <Group grow>
                    <TextInput
                      label="账号状态"
                      value={createDraft.accountState}
                      onChange={(event) => {
                        const value = event.currentTarget.value;
                        setCreateDraft((prev) => ({ ...prev, accountState: value }));
                      }}
                      placeholder="active / suspended / locked / pending_verification"
                    />
                    <Group gap="md" align="center" mt={26}>
                      <Checkbox
                        label="管理员"
                        checked={createDraft.isAdmin}
                        onChange={(event) => {
                          const checked = event.currentTarget.checked;
                          setCreateDraft((prev) => ({ ...prev, isAdmin: checked }));
                        }}
                      />
                      <Checkbox
                        label="启用"
                        checked={createDraft.isActive}
                        onChange={(event) => {
                          const checked = event.currentTarget.checked;
                          setCreateDraft((prev) => ({ ...prev, isActive: checked }));
                        }}
                      />
                    </Group>
                  </Group>
                  <Group gap="md">
                    {ROLE_OPTIONS.map((role) => (
                      <Checkbox
                        key={`create-role-${role}`}
                        label={role}
                        checked={createDraft.roles.includes(role)}
                        onChange={(event) => {
                          const checked = event.currentTarget.checked;
                          setCreateDraft((prev) => ({
                            ...prev,
                            roles: checked
                              ? [...prev.roles, role]
                              : prev.roles.filter((item) => item !== role),
                          }));
                        }}
                      />
                    ))}
                  </Group>
                  <Group justify="flex-end">
                    <Button loading={createUserMutation.isPending} onClick={() => createUserMutation.mutate()}>
                      创建账号
                    </Button>
                  </Group>
                </Stack>
              </Paper>

              <Paper p="md" radius="md" withBorder>
                {usersQuery.isLoading ? <Text size="sm">加载中...</Text> : null}
                {usersQuery.error ? (
                  <Alert color="red" title="读取用户失败">
                    {usersQuery.error instanceof Error ? usersQuery.error.message : "未知错误"}
                  </Alert>
                ) : null}
                {!usersQuery.isLoading && !usersQuery.error ? (
                  <Table striped highlightOnHover withTableBorder>
                    <Table.Thead>
                      <Table.Tr>
                        <Table.Th>用户名</Table.Th>
                        <Table.Th>显示名</Table.Th>
                        <Table.Th>角色</Table.Th>
                        <Table.Th>状态</Table.Th>
                        <Table.Th>最后登录</Table.Th>
                        <Table.Th>操作</Table.Th>
                      </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                      {(usersQuery.data?.items || []).map((item) => (
                        <Table.Tr key={`user-row-${item.id}`}>
                          <Table.Td>{item.username}</Table.Td>
                          <Table.Td>{item.display_name || "—"}</Table.Td>
                          <Table.Td>{item.roles.join(", ") || "—"}</Table.Td>
                          <Table.Td>
                            <Group gap={6}>
                              <Badge color={item.is_active ? "green" : "gray"} variant="light">
                                {item.is_active ? "启用" : "停用"}
                              </Badge>
                              <Badge color="blue" variant="light">{item.account_state}</Badge>
                            </Group>
                          </Table.Td>
                          <Table.Td>{formatDateTimeLabel(item.last_login_at)}</Table.Td>
                          <Table.Td>
                            <Group gap={6}>
                              <Button
                                size="xs"
                                variant="light"
                                onClick={() => {
                                  setEditingUser(toEditDraft(item));
                                  setActionError(null);
                                }}
                              >
                                编辑
                              </Button>
                              <Button
                                size="xs"
                                variant="light"
                                color={item.is_active ? "orange" : "teal"}
                                loading={suspendOrActivateMutation.isPending}
                                onClick={() => suspendOrActivateMutation.mutate(item)}
                              >
                                {item.is_active ? "停用" : "激活"}
                              </Button>
                              <Button
                                size="xs"
                                variant="light"
                                color="violet"
                                onClick={() => {
                                  setResetTarget(item);
                                  setResetPassword("");
                                  setActionError(null);
                                }}
                              >
                                重置密码
                              </Button>
                              <Button
                                size="xs"
                                variant="light"
                                color="red"
                                loading={deleteUserMutation.isPending}
                                onClick={() => {
                                  if (!window.confirm(`确定删除账号 ${item.username} 吗？`)) return;
                                  deleteUserMutation.mutate(item);
                                }}
                              >
                                删除
                              </Button>
                            </Group>
                          </Table.Td>
                        </Table.Tr>
                      ))}
                      {(usersQuery.data?.items || []).length === 0 ? (
                        <Table.Tr>
                          <Table.Td colSpan={6}>
                            <Text size="sm" c="dimmed">暂无账号数据</Text>
                          </Table.Td>
                        </Table.Tr>
                      ) : null}
                    </Table.Tbody>
                  </Table>
                ) : null}
              </Paper>

              {editingUser ? (
                <Paper p="md" radius="md" withBorder>
                  <Stack gap="sm">
                    <Text fw={700}>编辑账号：{editingUser.username}</Text>
                    <Group grow>
                      <TextInput
                        label="显示名称"
                        value={editingUser.displayName}
                        onChange={(event) => {
                          const value = event.currentTarget.value;
                          setEditingUser((prev) => (prev ? { ...prev, displayName: value } : prev));
                        }}
                      />
                      <TextInput
                        label="邮箱"
                        value={editingUser.email}
                        onChange={(event) => {
                          const value = event.currentTarget.value;
                          setEditingUser((prev) => (prev ? { ...prev, email: value } : prev));
                        }}
                      />
                    </Group>
                    <Group grow>
                      <TextInput
                        label="账号状态"
                        value={editingUser.accountState}
                        onChange={(event) => {
                          const value = event.currentTarget.value;
                          setEditingUser((prev) => (prev ? { ...prev, accountState: value } : prev));
                        }}
                        placeholder={ACCOUNT_STATE_OPTIONS.join(" / ")}
                      />
                      <Group gap="md" align="center" mt={26}>
                        <Checkbox
                          label="管理员"
                          checked={editingUser.isAdmin}
                          onChange={(event) => {
                            const checked = event.currentTarget.checked;
                            setEditingUser((prev) => (prev ? { ...prev, isAdmin: checked } : prev));
                          }}
                        />
                        <Checkbox
                          label="启用"
                          checked={editingUser.isActive}
                          onChange={(event) => {
                            const checked = event.currentTarget.checked;
                            setEditingUser((prev) => (prev ? { ...prev, isActive: checked } : prev));
                          }}
                        />
                      </Group>
                    </Group>
                    <Group gap="md">
                      {ROLE_OPTIONS.map((role) => (
                        <Checkbox
                          key={`edit-role-${role}`}
                          label={role}
                          checked={editingUser.roles.includes(role)}
                          onChange={(event) => {
                            const checked = event.currentTarget.checked;
                            setEditingUser((prev) => {
                              if (!prev) return prev;
                              return {
                                ...prev,
                                roles: checked
                                  ? [...prev.roles, role]
                                  : prev.roles.filter((item) => item !== role),
                              };
                            });
                          }}
                        />
                      ))}
                    </Group>
                    <Group justify="space-between">
                      <Button variant="subtle" color="gray" onClick={() => setEditingUser(null)}>
                        取消编辑
                      </Button>
                      <Group>
                        <Button
                          variant="light"
                          loading={updateRolesMutation.isPending}
                          onClick={() => editingUser && updateRolesMutation.mutate(editingUser)}
                        >
                          保存角色
                        </Button>
                        <Button
                          loading={updateUserMutation.isPending}
                          onClick={() => editingUser && updateUserMutation.mutate(editingUser)}
                        >
                          保存资料
                        </Button>
                      </Group>
                    </Group>
                  </Stack>
                </Paper>
              ) : null}

              {resetTarget ? (
                <Paper p="md" radius="md" withBorder>
                  <Stack gap="sm">
                    <Text fw={700}>重置密码：{resetTarget.username}</Text>
                    <TextInput
                      label="新密码"
                      value={resetPassword}
                      onChange={(event) => setResetPassword(event.currentTarget.value)}
                    />
                    <Group justify="space-between">
                      <Button variant="subtle" color="gray" onClick={() => setResetTarget(null)}>
                        取消
                      </Button>
                      <Button
                        loading={resetPasswordMutation.isPending}
                        onClick={() => {
                          if (!resetPassword.trim()) {
                            setActionError("重置密码不能为空");
                            return;
                          }
                          resetPasswordMutation.mutate();
                        }}
                      >
                        提交重置
                      </Button>
                    </Group>
                  </Stack>
                </Paper>
              ) : null}
            </Stack>
          </Tabs.Panel>

          <Tabs.Panel value="invites" pt="md">
            <Stack gap="md">
              <Paper p="md" radius="md" withBorder>
                <Stack gap="sm">
                  <Text fw={700}>创建邀请码</Text>
                  <Group grow>
                    <TextInput
                      label="角色"
                      value={inviteRole}
                      onChange={(event) => {
                        const value = event.currentTarget.value as RoleKey;
                        setInviteRole(ROLE_OPTIONS.includes(value) ? value : "viewer");
                      }}
                      placeholder={ROLE_OPTIONS.join(" / ")}
                    />
                    <NumberInput
                      label="可使用次数"
                      min={1}
                      max={1000}
                      value={inviteMaxUses}
                      onChange={(value) => setInviteMaxUses(Number(value) || 1)}
                    />
                  </Group>
                  <Group grow>
                    <TextInput
                      label="绑定邮箱（可选）"
                      value={inviteEmail}
                      onChange={(event) => setInviteEmail(event.currentTarget.value)}
                    />
                    <TextInput
                      label="自定义邀请码（可选）"
                      value={inviteCode}
                      onChange={(event) => setInviteCode(event.currentTarget.value)}
                    />
                  </Group>
                  <TextInput
                    label="备注（可选）"
                    value={inviteNote}
                    onChange={(event) => setInviteNote(event.currentTarget.value)}
                  />
                  <Group justify="flex-end">
                    <Button loading={createInviteMutation.isPending} onClick={() => createInviteMutation.mutate()}>
                      创建邀请码
                    </Button>
                  </Group>
                </Stack>
              </Paper>

              <Paper p="md" radius="md" withBorder>
                {invitesQuery.isLoading ? <Text size="sm">加载中...</Text> : null}
                {invitesQuery.error ? (
                  <Alert color="red" title="读取邀请码失败">
                    {invitesQuery.error instanceof Error ? invitesQuery.error.message : "未知错误"}
                  </Alert>
                ) : null}
                {!invitesQuery.isLoading && !invitesQuery.error ? (
                  <Table striped highlightOnHover withTableBorder>
                    <Table.Thead>
                      <Table.Tr>
                        <Table.Th>邀请码</Table.Th>
                        <Table.Th>角色</Table.Th>
                        <Table.Th>使用情况</Table.Th>
                        <Table.Th>状态</Table.Th>
                        <Table.Th>备注</Table.Th>
                        <Table.Th>操作</Table.Th>
                      </Table.Tr>
                    </Table.Thead>
                    <Table.Tbody>
                      {(invitesQuery.data?.items || []).map((item) => (
                        <Table.Tr key={`invite-row-${item.id}`}>
                          <Table.Td>
                            <Group gap={4} wrap="nowrap" style={{ width: "fit-content" }}>
                              <Text span style={{ whiteSpace: "nowrap" }}>
                                {item.code_hint}
                              </Text>
                              <Tooltip label="复制邀请码">
                                <ActionIcon
                                  variant="subtle"
                                  color="gray"
                                  aria-label="复制邀请码"
                                  onClick={() => {
                                    void copyInviteCode(item.code_hint);
                                  }}
                                >
                                  <IconCopy size={16} />
                                </ActionIcon>
                              </Tooltip>
                            </Group>
                          </Table.Td>
                          <Table.Td>{item.role_key}</Table.Td>
                          <Table.Td>{item.used_count}/{item.max_uses}</Table.Td>
                          <Table.Td>
                            <Badge color={item.disabled_at ? "gray" : "green"} variant="light">
                              {item.disabled_at ? "已停用" : "有效"}
                            </Badge>
                          </Table.Td>
                          <Table.Td>{item.note || "—"}</Table.Td>
                          <Table.Td>
                            <Group gap={6}>
                              {!item.disabled_at ? (
                                <Button
                                  size="xs"
                                  variant="light"
                                  color="orange"
                                  loading={disableInviteMutation.isPending}
                                  onClick={() => disableInviteMutation.mutate(item.id)}
                                >
                                  停用
                                </Button>
                              ) : null}
                              <Button
                                size="xs"
                                variant="light"
                                color="red"
                                loading={deleteInviteMutation.isPending}
                                onClick={() => {
                                  if (!window.confirm("确定删除该邀请码吗？删除后不可恢复。")) return;
                                  deleteInviteMutation.mutate(item.id);
                                }}
                              >
                                删除
                              </Button>
                            </Group>
                          </Table.Td>
                        </Table.Tr>
                      ))}
                      {(invitesQuery.data?.items || []).length === 0 ? (
                        <Table.Tr>
                          <Table.Td colSpan={6}>
                            <Text size="sm" c="dimmed">暂无邀请码</Text>
                          </Table.Td>
                        </Table.Tr>
                      ) : null}
                    </Table.Tbody>
                  </Table>
                ) : null}
              </Paper>
            </Stack>
          </Tabs.Panel>
        </Tabs>
      </SectionCard>
    </Stack>
  );
}

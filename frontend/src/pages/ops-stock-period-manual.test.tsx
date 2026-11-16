import { MantineProvider } from '@mantine/core';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { createMemoryHistory, RouterProvider, createRootRoute, createRouter } from '@tanstack/react-router';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, vi } from 'vitest';
import { appTheme } from '../app/theme';
import { AuthProvider } from '../features/auth/auth-context';
import { apiRequest } from '../shared/api/client';
import catalog from '../test/fixtures/stock-period-manual-actions.json';
import { OpsManualTaskTab } from './ops-v21-task-manual-tab';

// Catalog captured from ManualActionQueryService on 2026-11-16. The Python
// contract test compares the fixture with that producer, not a page-generated form.
vi.mock('../shared/api/client', () => ({apiRequest: vi.fn(async (path: string) => {
  if (path === '/api/v1/ops/manual-actions') return catalog;
  if (path.includes('/task-runs')) throw new Error('intent captured; no server started in this UI test');
  throw new Error(path);
})}));
beforeEach(() => { Element.prototype.scrollIntoView=vi.fn(); window.localStorage.clear(); vi.mocked(apiRequest).mockClear(); });
function page(kind='period', fields: Record<string, string>={}) {
  window.localStorage.setItem('goldenshare.frontend.ops.task-center.manual.draft', JSON.stringify({
    action_id:'stk_period_bar_adj_month.maintain',maintenance_kind:kind,time_mode:'point',
    selected_date:kind==='current_period'?'2026-11-13':'2020-02-29',field_values:fields,
    start_date:'',end_date:'',selected_month:'',start_month:'',end_month:''}));
  const entry='/app/ops/v21/datasets/tasks?tab=manual'; window.history.replaceState({},'',entry);
  const route=createRootRoute({component:()=><OpsManualTaskTab/>});
  const router=createRouter({routeTree:route,basepath:'/app',history:createMemoryHistory({initialEntries:[entry]})});
  render(<MantineProvider theme={appTheme} env="test"><QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false},mutations:{retry:false}}})}>
    <AuthProvider><RouterProvider router={router}/></AuthProvider>
  </QueryClientProvider></MantineProvider>);
}
const submit='/api/v1/ops/manual-actions/stk_period_bar_adj_month.maintain/task-runs';
it('当期更新提交业务交易日，源周期日期由后端决定', async () => {
  page('current_period'); (await screen.findAllByLabelText('处理用途')).find(el=>el.tagName==='INPUT' && (el as HTMLInputElement).type!=='hidden')!;
  expect(screen.queryByLabelText('证券代码')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'提交维护任务'}));
  await waitFor(()=>expect(apiRequest).toHaveBeenCalledWith(submit,{method:'POST',body:{
    time_input:{mode:'point',business_date:'2026-11-13'},filters:{},maintenance_intent:{kind:'current_period'}}}));
});
it('指定周期保留自然月末和股票输入；切换用途清除旧值', async () => {
  page('period',{ts_code:'000001.SZ'}); const purpose=(await screen.findAllByLabelText('处理用途')).find(el=>el.tagName==='INPUT' && (el as HTMLInputElement).type!=='hidden')!;
  fireEvent.click(screen.getByRole('button',{name:'提交维护任务'}));
  await waitFor(()=>expect(apiRequest).toHaveBeenCalledWith(submit,{method:'POST',body:{
    time_input:{mode:'point',trade_date:'2020-02-29'},filters:{ts_code:'000001.SZ'},maintenance_intent:{kind:'period'}}}));
});
it('切换处理用途清除不适用的股票和周期日期', async () => {
  page('period',{ts_code:'000001.SZ'}); await screen.findAllByLabelText('处理用途');
  const input=screen.getByRole('textbox',{name:'处理用途'});
  fireEvent.click(input); fireEvent.click(await screen.findByRole('option',{name:'当前周期更新'}));
  expect(screen.queryByDisplayValue('000001.SZ')).not.toBeInTheDocument();
  expect(screen.queryByDisplayValue('2020-02-29')).not.toBeInTheDocument();
});
it('恢复只提交原任务ID，隐藏新范围输入', async () => {
  page('current_period'); const resume=await screen.findByLabelText('续跑来源任务 ID（可选）');
  fireEvent.change(resume,{target:{value:'123'}});
  expect(await screen.findByText('按原任务续跑')).toBeInTheDocument();
  expect(screen.queryByLabelText('处理用途')).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole('button',{name:'提交维护任务'}));
  await waitFor(()=>expect(apiRequest).toHaveBeenCalledWith(submit,{method:'POST',body:{resume_from_task_run_id:123}}));
});

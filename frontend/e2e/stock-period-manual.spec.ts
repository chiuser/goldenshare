import { expect, test } from '@playwright/test';
import catalog from '../src/test/fixtures/stock-period-manual-actions.json' with {type:'json'};
import { installApiMocks, setAdminSession } from './support/smoke-fixtures';

test('股票复权月线用途切换、业务日提交和原任务恢复', async ({page}) => {
  const errors: string[]=[]; page.on('pageerror',error=>errors.push(error.message));
  const failed: string[]=[]; page.on('requestfailed',request=>failed.push(request.url()));
  await setAdminSession(page); await installApiMocks(page,'task-center');
  await page.route('**/api/v1/ops/manual-actions',route=>route.fulfill({json:catalog}));
  await page.route('**/api/v1/market/trade-calendar?**',route=>route.fulfill({json:{exchange:'SSE',items:[{trade_date:'2026-11-13',is_open:true,pretrade_date:'2026-11-12'}]}}));
  const bodies: unknown[]=[];
  await page.route('**/api/v1/ops/manual-actions/stk_period_bar_adj_month.maintain/task-runs',route=>{
    bodies.push(route.request().postDataJSON()); return route.fulfill({status:422,json:{code:'isolated_test',message:'本浏览器验证只核对提交体'}});
  });
  await page.addInitScript(()=>localStorage.setItem('goldenshare.frontend.ops.task-center.manual.draft',JSON.stringify({action_id:'stk_period_bar_adj_month.maintain',maintenance_kind:'period',time_mode:'point',selected_date:'2020-02-29',field_values:{ts_code:'000001.SZ'},start_date:'',end_date:'',selected_month:'',start_month:'',end_month:''})));
  await page.goto('/app/ops/v21/datasets/tasks?tab=manual');
  await expect(page.getByLabel('证券代码',{exact:true})).toHaveValue('000001.SZ');
  await expect(page.getByRole('textbox',{name:'处理用途',exact:true})).toHaveValue('指定周期维护');
  await page.getByRole('textbox',{name:'处理用途',exact:true}).click();
  await expect(page.getByRole('option',{name:'当前周期更新',exact:true})).toBeVisible();
  await page.getByRole('option',{name:'当前周期更新',exact:true}).click();
  await expect(page.getByLabel('证券代码',{exact:true})).toHaveCount(0);
  await expect(page.getByRole('button',{name:'选择日期',exact:true})).toHaveText('请选择日期');
  await page.getByRole('button',{name:'选择日期',exact:true}).click();
  await page.getByRole('button',{name:'February 2020',exact:true}).click();
  await page.getByRole('button',{name:'2020',exact:true}).click();
  await page.getByRole('button',{name:'2026',exact:true}).click();
  await page.getByRole('button',{name:/^Nov/}).click();
  await page.getByRole('button',{name:'13 November 2026',exact:true}).click();
  await page.getByRole('button',{name:'提交维护任务',exact:true}).click();
  await expect.poll(()=>bodies.length).toBe(1);
  expect(bodies[0]).toEqual({time_input:{mode:'point',business_date:'2026-11-13'},filters:{},maintenance_intent:{kind:'current_period'}});
  await page.getByLabel('续跑来源任务 ID（可选）',{exact:true}).fill('123');
  await expect(page.getByText('按原任务续跑',{exact:true})).toBeVisible();
  await expect(page.getByRole('textbox',{name:'处理用途',exact:true})).toHaveCount(0);
  await page.getByRole('button',{name:'提交维护任务',exact:true}).click();
  await expect.poll(()=>bodies.length).toBe(2); expect(bodies[1]).toEqual({resume_from_task_run_id:123});
  expect(errors).toEqual([]); expect(failed).toEqual([]);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});

test('股票复权月线自动任务使用后端固定探针配置',async ({page})=>{
  const {default: automation}=await import('../src/test/fixtures/stock-period-automation-catalog.json',{with:{type:'json'}});
  await setAdminSession(page); await installApiMocks(page,'task-auto');
  await page.route('**/api/v1/ops/catalog',route=>route.fulfill({json:automation}));
  let submitted: Record<string,unknown>|null=null;
  await page.route('**/api/v1/ops/schedules',route=>{
    if(route.request().method()!=='POST')return route.fallback();
    submitted=route.request().postDataJSON();
    return route.fulfill({json:{...submitted,id:201,status:'active',next_run_at:null}});
  });
  await page.goto('/app/ops/automation');
  await page.getByRole('button',{name:'新建自动任务'}).click();
  await page.getByRole('textbox',{name:'先选数据分组'}).click();
  await page.getByRole('option',{name:'A股行情',exact:true}).click();
  await page.getByRole('textbox',{name:'再选执行对象'}).click();
  await page.getByRole('option',{name:/股票月线行情（复权）/}).click();
  await expect(page.getByLabel('探测窗口开始')).toHaveValue('20:00');
  await expect(page.getByLabel('探测窗口结束')).toHaveValue('00:00');
  await expect(page.getByLabel('探测频率（秒）')).toHaveValue('60');
  await expect(page.getByLabel('证券代码',{exact:true})).toHaveCount(0);
  await page.getByLabel('任务名称',{exact:true}).fill('股票复权月线日更');
  await page.getByRole('button',{name:'创建自动任务',exact:true}).click();
  await expect.poll(()=>submitted).not.toBeNull();
  expect(submitted).toMatchObject({target_key:'stk_period_bar_adj_month.maintain',trigger_mode:'probe',timezone:'Asia/Shanghai',cron_expr:null,
    probe_config:{condition_kind:'stock_period_adj_current_ready',window_start:'20:00',window_end:'00:00',probe_interval_seconds:60,max_triggers_per_day:1}});
});

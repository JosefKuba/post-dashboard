<template>
<div class="app" :style="appStyle">
  <div v-if="!userToken" class="login-wrap"><div class="login-card"><h1>🌳 匈牙利帖文一览 🌳</h1><input v-model="loginPassword" type="password" placeholder="普通用户密码" @keyup.enter="loginUser"/><button @click="loginUser">登录</button><div class="err">{{ error }}</div></div></div>
  <template v-else>
    <header class="topbar"><h1>🌳 匈牙利帖文一览 🌳</h1><div class="top-actions"><button class="primary" @click="refreshData">刷新</button><button @click="showSettings=true">显示设置</button><button @click="showAdmin=true">管理中心</button><button @click="logout">退出</button></div></header>
    <section v-if="!isForeignRefPage" class="admin-tabs"><button :class="{active:filters.admin==='__all__'}" @click="setAdmin('__all__')">全部管理员</button><button v-for="a in admins" :key="a.name" :class="{active:filters.admin===a.name}" @click="setAdmin(a.name)">{{a.name}}</button></section>
    <section v-else class="admin-tabs"><button :class="{active:filters.ref_lang===''}" @click="setRefLang('')">全部语系</button><button v-for="l in refLangs" :key="l" :class="{active:filters.ref_lang===l}" @click="setRefLang(l)">{{l}}</button></section>
    <section class="page-tabs">
      <button v-for="p in mainPages" :key="p.key" :class="{active:activePage===p.key}" @click="setPage(p.key)">{{p.title}}</button>
      <span class="tabs-spacer"></span>
      <button v-for="p in queryPages" :key="p.key" class="query-tab" :class="{active:activePage===p.key}" @click="setPage(p.key)">{{p.title}}</button>
    </section>
    <div v-if="error" class="banner-err"><span>{{error}}</span><button class="banner-close" @click="error=''">×</button></div>
    <section v-if="isForeignRefPage" class="filters">
      <label>帖文类型<select v-model="filters.ref_post_type" @change="scheduleFilterLoad"><option value="">全部类型</option><option v-for="t in refPostTypes" :key="t" :value="t">{{t}}</option></select></label>
      <label>引流量最低值<input type="number" min="0" step="1" v-model.number="filters.ref_min_leads" @change="scheduleFilterLoad"/></label>
      <label>开始日期<input type="date" v-model="filters.ref_start_date" @change="onRefDateChange"/></label>
      <label>结束日期<input type="date" v-model="filters.ref_end_date" @change="onRefDateChange"/></label>
      <button :class="{active:!filters.ref_start_date&&!filters.ref_end_date}" @click="clearRefDates">全部日期</button>
      <span class="filter-hint">修改条件后自动查询</span>
    </section>
    <section v-else-if="!isQueryPage" class="filters">
      <label v-if="activePage==='posts'||activePage==='invitesOverview'||activePage==='onlineOverview'">日期类型<select v-model="filters.date_type" @change="scheduleFilterLoad"><option v-if="activePage==='posts'" value="lead">引流日期</option><option v-if="activePage==='posts'" value="post">发帖日期</option><option v-if="activePage!=='posts'" value="invite">邀约日期</option><option v-if="activePage!=='posts'" value="post">发帖日期</option></select></label>
      <label>开始日期<input type="date" v-model="filters.start_date" @change="onDateInputChange"/></label><label>结束日期<input type="date" v-model="filters.end_date" @change="onDateInputChange"/></label>
      <label>专页代码<select v-model="filters.page_code" @change="scheduleFilterLoad"><option value="">全部专页</option><option v-for="p in pages" :key="p.page_code" :value="p.page_code">{{p.page_code}}</option></select></label>
      <label v-if="activePage==='posts'||activePage==='leads'">引流最低值<input type="number" min="0" step="1" v-model.number="filters.min_leads" @change="scheduleFilterLoad"/></label>
      <template v-if="activePage==='church'"><button :class="{active:quickMode==='church_current'}" @click="setChurchCycle(0,'church_current')">本月</button><button :class="{active:quickMode==='church_prev'}" @click="setChurchCycle(1,'church_prev')">上月</button></template><template v-else><button :class="{active:quickMode==='today'}" @click="quickDay(0)">今日</button><button :class="{active:quickMode==='yesterday'}" @click="quickDay(1)">昨日</button><button :class="{active:quickMode==='before'}" @click="quickDay(2)">前日</button></template>
      <span class="filter-hint">修改条件后自动查询</span>
    </section>
    <section v-else class="query-panel">
      <div class="query-label">{{queryPanelTitle}}</div>
      <textarea v-model="queryText" class="query-textarea" :placeholder="queryPlaceholder" spellcheck="false"></textarea>
      <div class="query-actions">
        <button class="primary" @click="runQuery">查询</button>
        <button @click="clearQuery">清空</button>
        <span class="query-stats" v-if="queryStats.raw||queryStats.recognized||queryStats.returned">原始 {{queryStats.raw}} 行，识别 {{queryStats.recognized}} 条，返回 {{queryStats.returned}} 行<span v-if="unmatchedList.length">，未命中 {{unmatchedList.length}} 条</span></span>
      </div>
      <div v-if="unmatchedList.length" class="unmatched-box">
        <div class="unmatched-head"><b>未命中列表</b><button @click="copyUnmatched">复制未命中</button></div>
        <pre class="unmatched-list">{{unmatchedList.join('\n')}}</pre>
      </div>
    </section>
    <section class="view-tabs">
      <button :class="{active:ui.view==='table'}" @click="ui.view='table';saveLocal()">表格视图</button>
      <button :class="{active:ui.view==='landscape'}" @click="ui.view='landscape';saveLocal()">横版图片视图</button>
      <button :class="{active:ui.view==='portrait'}" @click="ui.view='portrait';saveLocal()">竖版图片视图</button>
      <button :disabled="!rows.length" @click="copyCurrentResults">复制</button>
      <span>共 {{total}} 条</span>
      <span v-if="loading" class="loading-inline">加载中…</span>
      <span v-if="copyToast" class="copy-toast">{{copyToast}}</span>
    </section>
    <div v-if="!loading && !rows.length" class="empty-state"><p>{{emptyMessage}}</p></div>
    <div v-if="ui.view==='table' && rows.length" class="table-wrap"><table :class="{noGrid:!ui.showGrid}"><thead><tr><th v-for="c in visibleColumns" :key="c.key" :style="headStyle(c)" :class="{sortable:isSortableColumn(c),sorted:filters.sort_by===sortKeyOf(c)}" @click="sortByColumn(c)"><span>{{c.label}}</span><span v-if="filters.sort_by===sortKeyOf(c)" class="sort-mark">{{filters.sort_dir==='asc'?'↑':'↓'}}</span></th><th :style="headStyle(actionCol)">操作</th></tr></thead><tbody><tr v-for="(r,idx) in rows" :key="r.post_id+'-'+idx" :style="rowStyle(idx)" :class="{rowActive:detailIndex===idx}"><td v-for="c in visibleColumns" :key="c.key" :style="cellStyle(c)"><Cell :row="r" :col="c" :ui="ui" @detail="openDetail"/></td><td :style="cellStyle(actionCol)"><button @click="openDetail(r,idx)">详情</button></td></tr></tbody></table></div>
    <div v-if="cellTip.show" class="cell-popover" :style="{left:cellTip.x+'px',top:cellTip.y+'px'}" @mouseenter="keepCellTip" @mouseleave="hideCellTip">
      <div class="cell-popover-text">{{cellTip.text}}</div>
      <button v-if="cellTip.copyable" class="cell-popover-copy" @click.stop="copyFromTip">复制全文</button>
    </div>
    <div v-else-if="ui.view!=='table' && rows.length" class="cards" :class="ui.view"><div v-for="(r,idx) in rows" :key="(r.lang_label||'')+'-'+r.post_id+'-'+idx" class="card" :class="{cardActive:detailIndex===idx}"><div class="media" :style="{aspectRatio:currentCardConfig.ratio}"><img v-if="imageOf(r)" :src="imageOf(r)"/><div v-else class="noimg">无图</div></div><div class="card-body"><div v-if="currentCardConfig.avatar" class="page-title"><Avatar :src="r.page_avatar" :label="r.lang_label||r.page_code"/> <b>{{isForeignRefPage?(r.lang_label||r.page_code):r.page_code}}</b></div><div class="id">{{r.post_id}}</div><div v-if="currentCardConfig.dates" class="meta"><template v-if="isForeignRefPage">发帖：{{formatDate(r.post_time)}}</template><template v-else>引流：{{formatDate(r.lead_date)}}　发帖：{{formatDate(r.post_time)}}</template></div><div v-if="currentCardConfig.gender && !isForeignRefPage" class="nums">{{genderRatio(r)}}</div><div v-if="currentCardConfig.metrics" class="nums"><template v-if="isForeignRefPage">引流量 {{r.leads}}</template><template v-else>引流 {{r.leads}} / 邀约 {{r.invites}} / 上线 {{r.online}} / 交教会 {{r.church}}</template></div><div v-if="currentCardConfig.engagement" class="nums">点赞 {{r.post_likes}} / 评论 {{r.post_comments}} / 分享 {{r.post_shares}}</div><div v-if="currentCardConfig.pageType" class="ptype">{{r.post_type}}</div><p v-if="currentCardConfig.summary">{{shortText(isForeignRefPage?(r.caption_zh||r.post_info_translation||r.caption_original||r.post_info):r.post_info)}}</p><div v-if="currentCardConfig.buttons" class="card-actions"><a :href="r.post_link" target="_blank">打开帖文</a><button @click="openDetail(r,idx)">查看详情</button></div></div></div></div>

    <!-- 详情：遮罩点击关闭；抽屉内上一条/下一条快速切换 -->
    <div v-if="detail" class="drawer-mask" @click="closeDetail"></div>
    <aside v-if="detail" class="drawer" :style="{width:Math.min(Math.max(ui.drawerWidth||480,480),640)+'px'}" @click.stop>
      <header class="drawer-head">
        <div class="drawer-nav">
          <button type="button" :disabled="!canDetailPrev" @click="detailNav(-1)">上一条</button>
          <button type="button" :disabled="!canDetailNext" @click="detailNav(1)">下一条</button>
          <span class="drawer-pos" v-if="detailIndex>=0">{{detailIndex+1}} / {{rows.length}}</span>
        </div>
        <button type="button" class="close" @click="closeDetail" title="关闭">×</button>
      </header>
      <div class="drawer-body">
        <!-- 上：图片 | 数据 左右排版 -->
        <div class="drawer-top">
          <div class="drawer-media">
            <div class="drawer-hero">
              <img v-if="imageOf(detail)" :src="imageOf(detail)" class="detail-img" alt=""/>
              <div v-else class="detail-noimg">无图</div>
            </div>
            <a v-if="detail.post_link" class="drawer-link" :href="detail.post_link" target="_blank" rel="noopener">打开原帖</a>
          </div>
          <div class="drawer-summary">
            <div class="drawer-title-row">
              <Avatar :src="detail.page_avatar" :label="detail.lang_label||detail.page_code"/>
              <div class="drawer-title-text">
                <b>{{isForeignRefPage?(detail.lang_label||detail.page_code||'—'):(detail.page_code||'—')}}</b>
                <span class="muted" v-if="!isForeignRefPage">{{detail.admin_name||'—'}}</span>
                <span class="muted" v-else>{{detail.post_type||'外语系参考'}}</span>
              </div>
            </div>
            <div class="detail-stats" :class="{refStats:isForeignRefPage}">
              <span><em>{{isForeignRefPage?'引流量':'引流'}}</em>{{detail.leads??0}}</span>
              <template v-if="!isForeignRefPage">
                <span><em>邀约</em>{{detail.invites??0}}</span>
                <span><em>上线</em>{{detail.online??0}}</span>
                <span><em>交教会</em>{{detail.church??0}}</span>
              </template>
            </div>
            <div class="detail-meta">
              <div v-if="isForeignRefPage"><label>语系</label><span>{{detail.lang_label||'—'}}</span></div>
              <div v-else><label>引流日</label><span>{{formatDate(detail.lead_date)||'—'}}</span></div>
              <div><label>发帖日</label><span>{{formatDate(detail.post_time)||'—'}}</span></div>
              <div v-if="!isForeignRefPage"><label>男女比</label><span>{{genderRatio(detail)}}</span></div>
              <div><label>类型</label><span>{{detail.post_type||'—'}}</span></div>
              <div class="full"><label>互动</label><span>赞 {{detail.post_likes??0}} · 评 {{detail.post_comments??0}} · 享 {{detail.post_shares??0}}</span></div>
              <div class="full"><label>帖文ID</label><span class="mono">{{detail.post_id||'—'}}</span></div>
              <div class="full" v-if="!isForeignRefPage && (detail.summary_source_name||detail.summary_source_sheet)"><label>来源</label><span>{{detail.summary_source_name}} / {{detail.summary_source_sheet}}</span></div>
            </div>
          </div>
        </div>
        <!-- 下：文案区块（始终展示，空内容显示占位） -->
        <div class="drawer-texts">
          <section v-for="s in detailSections" :key="s.title" class="drawer-section" :class="{empty:!s.hasText}">
            <div class="drawer-section-head">
              <h3>{{s.title}}</h3>
              <button v-if="s.hasText" type="button" class="sec-copy" @click="copyText(s.text,'已复制 '+s.title)">复制</button>
            </div>
            <pre class="drawer-pre">{{s.hasText?s.text:'（暂无内容）'}}</pre>
          </section>
        </div>
      </div>
    </aside>
    <div v-if="showSettings" class="modal-mask"><div class="modal settings-modal"><h2>显示设置</h2><div class="modal-actions"><button @click="exportStyle">导出当前样式配置</button><label class="import-btn">导入样式配置<input type="file" accept="application/json" @change="importStyle" hidden/></label><button @click="restoreAdminDefault">恢复管理员默认设置</button><button @click="resetLocal">清除本浏览器样式</button><button @click="showSettings=false">关闭</button></div><div class="settings-grid"><section><h3>基础样式</h3><label>字体大小<input type="number" v-model.number="ui.fontSize"/></label><label>行高<input type="number" v-model.number="ui.rowHeight"/></label><label>图片大小<input type="number" v-model.number="ui.imageSize"/></label><label>摘要字数<input type="number" v-model.number="ui.textLimit"/></label><label>详情宽度<input type="number" v-model.number="ui.drawerWidth"/></label><label><input type="checkbox" v-model="ui.showGrid"/>显示表格线</label><label>表头背景<input type="color" v-model="ui.headerBg"/></label><label>表头文字<input type="color" v-model="ui.headerColor"/></label><label>普通文字<input type="color" v-model="ui.textColor"/></label><label>表格线<input type="color" v-model="ui.gridColor"/></label><label>隔行底色<input type="color" v-model="ui.stripeBg"/></label><label>悬停底色<input type="color" v-model="ui.hoverBg"/></label></section><section><h3>图片视图</h3><div class="card-config"><h4>横版</h4><label v-for="f in cardFieldOptions" :key="'l'+f.key"><input type="checkbox" v-model="ui.landscape[f.key]"/>{{f.label}}</label><label>比例<input v-model="ui.landscape.ratio"/></label></div><div class="card-config"><h4>竖版</h4><label v-for="f in cardFieldOptions" :key="'p'+f.key"><input type="checkbox" v-model="ui.portrait[f.key]"/>{{f.label}}</label><label>比例<input v-model="ui.portrait.ratio"/></label></div></section></div><section><h3>表格列设置（可拖动，也可用按钮）</h3><div class="column-settings"><div v-for="(c,i) in sortedAllColumns" :key="c.key" class="column-row" draggable="true" @dragstart="dragIndex=i" @dragover.prevent @drop="dropColumn(i)"><span class="drag">☰</span><input type="checkbox" v-model="c.visible"/><input class="label-input" v-model="c.label" placeholder="表头名"/><input type="number" v-model.number="c.width"/><select v-model="c.align"><option value="left">左</option><option value="center">中</option><option value="right">右</option></select><select v-model="c.displayMode"><option value="single">单行</option><option value="clip">截断</option><option value="wrap">换行</option><option value="lines">限制行数</option></select><input type="number" v-model.number="c.maxLines"/><label><input type="checkbox" v-model="c.detailOnly"/>只详情</label><button @click="moveColumn(i,-1)">上</button><button @click="moveColumn(i,1)">下</button><button @click="moveTop(i)">顶</button><button @click="moveBottom(i)">底</button></div></div></section><div class="modal-actions"><button @click="saveLocal();showSettings=false">保存到当前浏览器</button><button @click="showSettings=false">关闭</button></div></div></div>
    <div v-if="showAdmin" class="modal-mask"><div class="modal admin-modal"><h2>管理中心</h2><div v-if="!adminToken"><input v-model="adminPassword" type="password" placeholder="管理员密码" @keyup.enter="loginAdmin"/><button @click="loginAdmin">登录管理中心</button></div><div v-else class="admin-actions"><button @click="runSync">立即同步全部数据</button><button @click="runSyncForeign">同步外语系参考</button><button @click="saveAdminUi">保存当前样式为管理员默认</button><button @click="clearSyncCache">清空同步缓存</button><button @click="loadLogs">刷新同步日志</button><button @click="showAdmin=false">关闭</button><h3>同步日志</h3><table class="admin-table"><tr><th>ID</th><th>状态</th><th>信息</th><th>开始</th><th>结束</th></tr><tr v-for="l in logs" :key="l.id"><td>{{l.id}}</td><td>{{l.status}}</td><td class="log-msg">{{l.message}}</td><td>{{l.started_at}}</td><td>{{l.finished_at}}</td></tr></table></div><div class="err">{{adminError}}</div></div></div>
  </template>
</div>
</template>
<script setup>
import { computed, defineComponent, h, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
const USER_KEY='POST_DASHBOARD_USER_TOKEN_V11', ADMIN_KEY='POST_DASHBOARD_ADMIN_TOKEN_V11', LOCAL_KEY='POST_DASHBOARD_LOCAL_STATE_V12'
const COLUMNS_LAYOUT_VERSION=15
const userToken=ref(localStorage.getItem(USER_KEY)||''), adminToken=ref(localStorage.getItem(ADMIN_KEY)||''), loginPassword=ref(''), adminPassword=ref(''), error=ref(''), adminError=ref('')
const admins=ref([]), pages=ref([]), rows=ref([]), total=ref(0), loading=ref(false), detail=ref(null), showSettings=ref(false), showAdmin=ref(false), logs=ref([]), activePage=ref('posts'), dragIndex=ref(null)
const mainPages=[{key:'posts',title:'引流帖文'},{key:'leads',title:'引流排行榜'},{key:'invitesOverview',title:'邀约帖文'},{key:'onlineOverview',title:'上线帖文'},{key:'church',title:'交教会帖文'},{key:'foreignRef',title:'外语系参考'}]
const queryPages=[{key:'queryPostId',title:'帖文 ID 查询'},{key:'queryPostLink',title:'帖文链接查询'},{key:'queryLeadId',title:'线索 ID 查询'}]
const functionPages=[...mainPages,...queryPages]
const QUERY_PAGE_KEYS=new Set(queryPages.map(p=>p.key))
const queryText=ref('')
const queryStats=reactive({raw:0,recognized:0,returned:0,unmatched:0})
const unmatchedList=ref([])
const isQueryPage=computed(()=>QUERY_PAGE_KEYS.has(activePage.value))
const isForeignRefPage=computed(()=>activePage.value==='foreignRef')
const refLangs=ref([])
const refPostTypes=ref([])
const queryPanelTitle=computed(()=>{
  if(activePage.value==='queryPostId') return '粘贴包含帖文ID的数据'
  if(activePage.value==='queryPostLink') return '粘贴包含帖文链接的数据'
  if(activePage.value==='queryLeadId') return '粘贴包含客户ID的数据（两列：线索ID + 加友渠道）'
  return '粘贴查询数据'
})
const queryPlaceholder=computed(()=>{
  if(activePage.value==='queryPostId') return '可直接从表格复制帖文ID后粘贴到这里（每行一个；无 # 时查询会自动补上）'
  if(activePage.value==='queryPostLink') return '可直接从表格复制帖文链接后粘贴到这里（每行一个）'
  if(activePage.value==='queryLeadId') return '可直接从表格复制多列数据后粘贴到这里（第一列线索ID，第二列加友渠道）'
  return ''
})
const emptyMessage=computed(()=>{
  if(loading.value) return ''
  if(isQueryPage.value){
    if(!queryText.value.trim()) return '请粘贴数据后点击「查询」'
    if(unmatchedList.value.length && !rows.value.length) return '未查询到匹配帖文，请查看上方未命中列表'
    return '未查询到匹配帖文'
  }
  if(activePage.value==='foreignRef') return '当前条件下暂无外语系参考帖文。可试试：切换语系、放宽引流量、清空日期，或在管理中心同步外语系参考'
  if(activePage.value==='church') return '当前周期暂无交教会帖文，可切换「上月」或调整日期范围'
  if(activePage.value==='leads') return '当前条件下暂无引流数据，可放宽「引流最低值」或换日期'
  if(activePage.value==='invitesOverview') return '当前条件下暂无邀约帖文，可换日期或管理员'
  if(activePage.value==='onlineOverview') return '当前条件下暂无上线帖文，可换日期或管理员'
  return '当前条件下暂无帖文。可试试：放宽引流最低值、换日期，或切换管理员'
})
// 默认精简列：媒体/专页/管理员/核心指标/引流日/链接/ID；其余默认隐藏，详情中仍可查看
const baseColumns=[
  // 列宽按常见内容：专页「匈FB专页187」、管理员「小王」、指标≤3位、日期 YYYY-MM-DD、FB 帖文ID
  {key:'display_media',label:'媒体',type:'image',width:76,align:'center',order:1,visible:true,detailOnly:false,displayMode:'single',maxLines:1},
  {key:'page_code',label:'专页',type:'text',width:128,align:'left',order:2,visible:true,detailOnly:false,displayMode:'single',maxLines:1},
  {key:'page_avatar',label:'头像',type:'avatar',width:52,align:'center',order:3,visible:false,detailOnly:false,displayMode:'single',maxLines:1},
  {key:'admin_name',label:'管理员',type:'text',width:56,align:'center',order:4,visible:true,detailOnly:false,displayMode:'single',maxLines:1},
  {key:'query_lead_id',label:'线索ID',type:'text',width:120,align:'left',order:4.5,visible:false,detailOnly:false,displayMode:'single',maxLines:1},
  {key:'query_friend_channel',label:'加友渠道',type:'text',width:120,align:'left',order:4.6,visible:false,detailOnly:false,displayMode:'single',maxLines:1},
  {key:'leads',label:'引流',type:'number',width:48,align:'center',order:5,visible:true,detailOnly:false,displayMode:'single',maxLines:1},
  {key:'invites',label:'邀约',type:'number',width:48,align:'center',order:6,visible:true,detailOnly:false,displayMode:'single',maxLines:1},
  {key:'online',label:'上线',type:'number',width:48,align:'center',order:7,visible:true,detailOnly:false,displayMode:'single',maxLines:1},
  {key:'church',label:'交教会',type:'number',width:56,align:'center',order:8,visible:true,detailOnly:false,displayMode:'single',maxLines:1},
  {key:'lead_date',label:'引流日',type:'date',width:100,align:'center',order:9,visible:true,detailOnly:false,displayMode:'single',maxLines:1},
  {key:'post_link',label:'链接',type:'link',width:52,align:'center',order:10,visible:true,detailOnly:false,displayMode:'single',maxLines:1},
  {key:'post_id',label:'ID',type:'text',width:200,align:'left',order:11,visible:false,detailOnly:false,displayMode:'single',maxLines:1},
  {key:'post_ocr_translation',label:'OCR译文',type:'text',width:240,align:'left',order:12,visible:true,detailOnly:false,displayMode:'lines',maxLines:2},
  {key:'video_translation',label:'视频译文',type:'text',width:240,align:'left',order:13,visible:true,detailOnly:false,displayMode:'lines',maxLines:2},
  {key:'gender_ratio',label:'男女比',type:'gender_ratio',width:120,align:'center',order:14,visible:false,detailOnly:false,displayMode:'single',maxLines:1},
  {key:'post_type',label:'类型',type:'text',width:140,align:'left',order:15,visible:false,detailOnly:false,displayMode:'single',maxLines:1},
  {key:'post_time',label:'发帖日',type:'date',width:100,align:'center',order:16,visible:false,detailOnly:false,displayMode:'single',maxLines:1},
  {key:'post_likes',label:'点赞',type:'number',width:56,align:'center',order:17,visible:false,detailOnly:false,displayMode:'single',maxLines:1},
  {key:'post_comments',label:'评论',type:'number',width:56,align:'center',order:18,visible:false,detailOnly:false,displayMode:'single',maxLines:1},
  {key:'post_shares',label:'分享',type:'number',width:56,align:'center',order:19,visible:false,detailOnly:false,displayMode:'single',maxLines:1},
  {key:'post_info',label:'内容',type:'text',width:260,align:'left',order:20,visible:false,detailOnly:false,displayMode:'lines',maxLines:2},
  {key:'post_info_translation',label:'内容译文',type:'text',width:260,align:'left',order:21,visible:false,detailOnly:false,displayMode:'lines',maxLines:2},
  {key:'post_ocr',label:'帖文OCR',type:'text',width:260,align:'left',order:22,visible:false,detailOnly:false,displayMode:'lines',maxLines:2},
  {key:'video_original',label:'视频原文',type:'text',width:260,align:'left',order:23,visible:false,detailOnly:false,displayMode:'lines',maxLines:2},
  {key:'summary_source_name',label:'来源',type:'text',width:120,align:'left',order:24,visible:false,detailOnly:false,displayMode:'single',maxLines:1}
]
const foreignRefColumns=[
  {key:'display_media',label:'媒体',type:'image',width:76,align:'center',order:1,visible:true,detailOnly:false,displayMode:'single',maxLines:1},
  {key:'lang_label',label:'语系',type:'text',width:88,align:'center',order:2,visible:true,detailOnly:false,displayMode:'single',maxLines:1},
  {key:'leads',label:'引流量',type:'number',width:72,align:'center',order:3,visible:true,detailOnly:false,displayMode:'single',maxLines:1},
  {key:'post_type',label:'帖文类型',type:'text',width:88,align:'center',order:4,visible:true,detailOnly:false,displayMode:'single',maxLines:1},
  {key:'caption_zh',label:'图片中文',type:'text',width:280,align:'left',order:5,visible:true,detailOnly:false,displayMode:'lines',maxLines:2},
  {key:'caption_original',label:'图片文案',type:'text',width:240,align:'left',order:6,visible:false,detailOnly:false,displayMode:'lines',maxLines:2},
  {key:'post_time',label:'发帖日',type:'date',width:100,align:'center',order:7,visible:true,detailOnly:false,displayMode:'single',maxLines:1},
  {key:'post_likes',label:'点赞',type:'number',width:80,align:'center',order:8,visible:true,detailOnly:false,displayMode:'single',maxLines:1},
  {key:'post_comments',label:'评论',type:'number',width:72,align:'center',order:9,visible:true,detailOnly:false,displayMode:'single',maxLines:1},
  {key:'post_shares',label:'分享',type:'number',width:72,align:'center',order:10,visible:true,detailOnly:false,displayMode:'single',maxLines:1},
  {key:'post_link',label:'链接',type:'link',width:52,align:'center',order:11,visible:true,detailOnly:false,displayMode:'single',maxLines:1},
  {key:'post_id',label:'ID',type:'text',width:200,align:'left',order:12,visible:false,detailOnly:false,displayMode:'single',maxLines:1}
]
const actionCol={key:'action',width:72,align:'center'}
const cardFieldOptions=[{key:'avatar',label:'专页头像'},{key:'dates',label:'日期'},{key:'gender',label:'男女比例'},{key:'metrics',label:'核心数据'},{key:'engagement',label:'互动数据'},{key:'pageType',label:'帖文类型'},{key:'summary',label:'帖文摘要'},{key:'buttons',label:'按钮'}]
const ui=reactive({version:'v12',columnsLayoutVersion:COLUMNS_LAYOUT_VERSION,view:'table',fontSize:13,rowHeight:42,imageSize:72,textLimit:80,drawerWidth:520,showGrid:true,headerBg:'#f8fafc',headerColor:'#111827',textColor:'#111827',gridColor:'#e5e7eb',stripeBg:'#ffffff',hoverBg:'#eef6ff',globalMinLeads:2,adminMinLeads:{},genderMode:'count_percent',landscape:{ratio:'16/9',avatar:true,dates:true,gender:true,metrics:true,engagement:true,pageType:true,summary:true,buttons:true},portrait:{ratio:'9/16',avatar:true,dates:true,gender:true,metrics:true,engagement:false,pageType:true,summary:false,buttons:true},columns:[]})
const filters=reactive({admin:'__all__',date_type:'lead',start_date:todayStr(),end_date:todayStr(),page_code:'',sort_by:'',sort_dir:'desc',min_leads:2,ref_lang:'',ref_post_type:'',ref_min_leads:0,ref_start_date:'',ref_end_date:''})
// 日期、帖文ID 等无需悬停弹框的列
const NO_TIP_KEYS=new Set(['lead_date','post_id','post_time'])
const COPYABLE_KEYS=new Set(['post_ocr_translation','video_translation','caption_zh','caption_original'])
const cellTip=reactive({show:false,text:'',x:0,y:0,copyable:false})
const copyToast=ref('')
let cellTipHideTimer=null
let copyToastTimer=null
function flashCopyToast(msg){
  copyToast.value=msg
  clearTimeout(copyToastTimer)
  copyToastTimer=setTimeout(()=>{copyToast.value=''},1800)
}
function isCellTruncated(el,text,col){
  if(!el)return false
  if(el.scrollWidth>el.clientWidth+1||el.scrollHeight>el.clientHeight+1)return true
  const s=String(text||'')
  if(!s)return false
  const mode=col?.displayMode||'single'
  const width=el.clientWidth||col?.width||200
  const charsPerLine=Math.max(6,Math.floor(width/((ui.fontSize||13)*0.95)))
  if(mode==='lines'){
    const maxLines=col.maxLines||2
    return s.length>charsPerLine*maxLines||(s.includes('\n')&&s.split('\n').length>maxLines)
  }
  if(mode==='wrap')return false
  return s.length>charsPerLine
}
function showCellTip(e,text,col){
  if(col?.type==='date'||NO_TIP_KEYS.has(col?.key)){cellTip.show=false;return}
  const s=text==null?'':String(text)
  if(!s.trim()){cellTip.show=false;return}
  const el=e.currentTarget
  if(!isCellTruncated(el,s,col)){cellTip.show=false;return}
  clearTimeout(cellTipHideTimer)
  const rect=el.getBoundingClientRect()
  const maxW=Math.min(420,window.innerWidth-24)
  let x=rect.left
  let y=rect.bottom+6
  if(x+maxW>window.innerWidth-12)x=Math.max(12,window.innerWidth-maxW-12)
  if(y>window.innerHeight-120)y=Math.max(12,rect.top-8)
  cellTip.text=s
  cellTip.x=x
  cellTip.y=y
  cellTip.copyable=COPYABLE_KEYS.has(col?.key)
  cellTip.show=true
}
function hideCellTip(){
  clearTimeout(cellTipHideTimer)
  cellTipHideTimer=setTimeout(()=>{cellTip.show=false},120)
}
function keepCellTip(){clearTimeout(cellTipHideTimer)}
async function copyFromTip(){
  if(!cellTip.text)return
  await copyText(cellTip.text,'已复制全文')
}
function textClampStyle(col){
  const mode=col.displayMode||'single'
  const style={minWidth:0,maxWidth:'100%'}
  if(mode==='lines'||mode==='wrap'){
    style.display='-webkit-box'
    style.WebkitLineClamp=mode==='wrap'?99:(col.maxLines||2)
    style.WebkitBoxOrient='vertical'
    style.overflow='hidden'
    style.whiteSpace='normal'
    style.wordBreak='break-word'
    style.lineHeight='1.35'
  }else{
    style.display='block'
    style.overflow='hidden'
    style.textOverflow='ellipsis'
    style.whiteSpace='nowrap'
  }
  return style
}
function tippableText(text,col){
  const s=text==null?'':String(text)
  if(!s)return ''
  const allowTip=!(col?.type==='date'||NO_TIP_KEYS.has(col?.key))
  return h('span',{
    class:'cell-text',
    style:textClampStyle(col),
    onMouseenter:allowTip?(e=>showCellTip(e,s,col)):undefined,
    onMouseleave:allowTip?hideCellTip:undefined
  },s)
}
const Avatar=defineComponent({props:{src:String,label:String},setup(p){const broken=ref(false);watch(()=>p.src,()=>{broken.value=false});return()=>!p.src||broken.value?h('span',{class:'avatar avatar-empty'},avatarText(p.label)):h('img',{class:'avatar',src:p.src,onError:()=>{broken.value=true}})}})
const Cell=defineComponent({props:{row:Object,col:Object,ui:Object},emits:['detail'],setup(props){return()=>renderCell(props.row,props.col,props.ui)}})
function renderCell(row,col,ui){
  if(col.type==='avatar')return h(Avatar,{src:row.page_avatar,label:row.page_code||row.admin_name||''})
  if(col.type==='image'){const src=imageOf(row); return src?h('img',{class:'thumb',style:{width:ui.imageSize+'px',height:ui.imageSize+'px'},src}):'-'}
  if(col.type==='link')return row[col.key]?h('a',{href:row[col.key],target:'_blank'},'打开'):''
  return tippableText(formatCell(row,col),col)
}
const detailIndex=ref(-1)
const canDetailPrev=computed(()=>detailIndex.value>0)
const canDetailNext=computed(()=>detailIndex.value>=0&&detailIndex.value<rows.value.length-1)
const detailSections=computed(()=>{
  if(!detail.value)return []
  const d=detail.value
  const blocks=isForeignRefPage.value?[
    {title:'图片文案',text:d.caption_original||d.post_info},
    {title:'图片中文',text:d.caption_zh||d.post_info_translation}
  ]:[
    {title:'帖文信息',text:d.post_info},
    {title:'帖文信息翻译',text:d.post_info_translation},
    {title:'帖文OCR',text:d.post_ocr},
    {title:'OCR译文',text:d.post_ocr_translation},
    {title:'视频原文',text:d.video_original},
    {title:'视频译文',text:d.video_translation}
  ]
  return blocks.map(s=>{
    const text=s.text==null?'':String(s.text)
    return {...s,text,hasText:text.trim()!==''}
  })
})
const appStyle=computed(()=>({fontSize:ui.fontSize+'px',color:ui.textColor,'--grid-color':ui.gridColor,'--hover-bg':ui.hoverBg}))
const sortedAllColumns=computed(()=>ui.columns.sort((a,b)=>(a.order||0)-(b.order||0)))
const visibleColumns=computed(()=>{
  if(isForeignRefPage.value)return foreignRefColumns.filter(c=>c.visible&&!c.detailOnly)
  const cols=sortedAllColumns.value.filter(c=>c.visible&&!c.detailOnly)
  if(activePage.value!=='queryLeadId')return cols.filter(c=>c.key!=='query_lead_id'&&c.key!=='query_friend_channel')
  const hasLead=cols.some(c=>c.key==='query_lead_id')
  const hasCh=cols.some(c=>c.key==='query_friend_channel')
  const extras=[]
  if(!hasLead)extras.push({key:'query_lead_id',label:'线索ID',type:'text',width:120,align:'left',order:0,visible:true,detailOnly:false,displayMode:'single',maxLines:1})
  if(!hasCh)extras.push({key:'query_friend_channel',label:'加友渠道',type:'text',width:140,align:'left',order:0,visible:true,detailOnly:false,displayMode:'single',maxLines:1})
  if(!extras.length)return cols
  // 插到管理员列之后
  const idx=cols.findIndex(c=>c.key==='admin_name')
  if(idx<0)return [...extras,...cols]
  return [...cols.slice(0,idx+1),...extras,...cols.slice(idx+1)]
})
const currentCardConfig=computed(()=>ui.view==='portrait'?ui.portrait:ui.landscape)
const quickMode=ref('today')
function pad2(n){return String(n).padStart(2,'0')}
function makeYmd(y,m,d){return `${y}-${pad2(m)}-${pad2(d)}`}
function addMonthsYm(y,m,delta){let total=y*12+(m-1)+delta;return {y:Math.floor(total/12),m:total%12+1}}
function parisYmdParts(){const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'Europe/Paris',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());return {y:Number(parts.find(p=>p.type==='year').value),m:Number(parts.find(p=>p.type==='month').value),d:Number(parts.find(p=>p.type==='day').value)}}
function todayStr(o=0){const d=new Date();d.setDate(d.getDate()-o);return makeYmd(d.getFullYear(),d.getMonth()+1,d.getDate())}
function monthStartStr(){const d=new Date();d.setDate(1);return makeYmd(d.getFullYear(),d.getMonth()+1,d.getDate())}
function ymd(d){return makeYmd(d.getFullYear(),d.getMonth()+1,d.getDate())}
function churchCycle(offset=0){const p=parisYmdParts();let sy,sm,ey,em;if(p.d>=23){sy=p.y;sm=p.m;const n=addMonthsYm(p.y,p.m,1);ey=n.y;em=n.m}else{const prev=addMonthsYm(p.y,p.m,-1);sy=prev.y;sm=prev.m;ey=p.y;em=p.m}if(offset){const s2=addMonthsYm(sy,sm,-offset);const e2=addMonthsYm(ey,em,-offset);sy=s2.y;sm=s2.m;ey=e2.y;em=e2.m}return {start:makeYmd(sy,sm,23),end:makeYmd(ey,em,22)}}
function setChurchCycle(offset=0,mode='church_current'){const c=churchCycle(offset);filters.start_date=c.start;filters.end_date=c.end;quickMode.value=mode;saveLocal();loadData()}
function headers(extra={}){return {'Content-Type':'application/json','X-User-Token':userToken.value,'X-Admin-Token':adminToken.value,...extra}}
async function api(url,opt={}){const res=await fetch(url,{...opt,headers:headers(opt.headers||{})}); if(!res.ok)throw new Error(await res.text()); return res.json()}
async function loginUser(){error.value='';try{const r=await fetch('/api/auth/user',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:loginPassword.value})}); if(!r.ok)throw new Error('密码错误'); const d=await r.json(); userToken.value=d.token; localStorage.setItem(USER_KEY,d.token); await init()}catch(e){error.value=e.message}}
function logout(){localStorage.removeItem(USER_KEY);localStorage.removeItem(ADMIN_KEY);userToken.value='';adminToken.value=''}
async function init(){await loadUi();restoreLocal();normalizeUi();await loadAdmins();await loadPages();if(isQueryPage.value){if(queryText.value.trim())await runQuery()}else{if(isForeignRefPage.value)await loadRefMeta();await loadData()}}
async function loadRefMeta(){
  try{
    const q=new URLSearchParams()
    if(filters.ref_lang)q.set('lang',filters.ref_lang)
    const d=await api('/api/reference/meta'+(q.toString()?'?'+q.toString():''))
    refLangs.value=Array.isArray(d.langs)?d.langs:[]
    refPostTypes.value=Array.isArray(d.post_types)?d.post_types:[]
    if(filters.ref_post_type && !refPostTypes.value.includes(filters.ref_post_type))filters.ref_post_type=''
  }catch(e){
    refLangs.value=[]
    refPostTypes.value=[]
  }
}
function setRefLang(lang){
  filters.ref_lang=lang||''
  filters.ref_post_type=''
  saveLocal()
  loadRefMeta().then(()=>{if(!isQueryPage.value)loadData()})
}
function onRefDateChange(){scheduleFilterLoad()}
function clearRefDates(){filters.ref_start_date='';filters.ref_end_date='';saveLocal();loadData()}
async function loadUi(){const remote=await api('/api/settings/ui');Object.assign(ui,remote);normalizeUi();setMinLeadsByAdmin()}
function normalizeUi(){
  const hiddenColumnKeys=new Set(['answers','gained','male','female'])
  if(!Array.isArray(ui.columns)||ui.columns.length===0)ui.columns=baseColumns.map(c=>({...c}))
  const hadMaleFemale=ui.columns.some(c=>c&&(c.key==='male'||c.key==='female'))
  ui.columns=ui.columns.map(c=>c&&c.key==='page_post_type'?{...c,key:'post_type'}:c)
  const seenKeys=new Set()
  ui.columns=ui.columns.filter(c=>{
    if(!c||hiddenColumnKeys.has(c.key)||seenKeys.has(c.key))return false
    seenKeys.add(c.key)
    return true
  })
  const known=new Set(ui.columns.map(c=>c.key))
  baseColumns.forEach(c=>{if(!known.has(c.key))ui.columns.push({...c,order:ui.columns.length+1})})
  // 合并 base 元数据；若列布局版本落后，采用新的默认显隐与顺序
  const upgradeLayout=(Number(ui.columnsLayoutVersion)||0)<COLUMNS_LAYOUT_VERSION
  ui.columns=ui.columns.map((c,i)=>{
    const base=baseColumns.find(b=>b.key===c.key)
    if(!base)return null
    if(upgradeLayout)return {...base,...c,visible:base.visible,order:base.order??c.order??i+1,width:base.width}
    return {...base,...c,order:c.order??base.order??i+1}
  }).filter(Boolean)
  if(upgradeLayout)ui.columnsLayoutVersion=COLUMNS_LAYOUT_VERSION
  ui.version=ui.version||'v12'
  if(hadMaleFemale){const ratioCol=ui.columns.find(c=>c.key==='gender_ratio'); if(ratioCol)ratioCol.visible=true}
  if(filters.sort_by==='gained'||filters.sort_by==='answers')filters.sort_by=''
  ;['landscape','portrait'].forEach(k=>ui[k]={...(k==='landscape'?{ratio:'16/9'}:{ratio:'9/16'}),avatar:true,dates:true,gender:true,metrics:true,engagement:k==='landscape',pageType:true,summary:k==='landscape',buttons:true,...(ui[k]||{})})
}
function setMinLeadsByAdmin(){filters.min_leads=filters.admin!=='__all__'?(ui.adminMinLeads?.[filters.admin]??ui.globalMinLeads):ui.globalMinLeads}
async function loadAdmins(){admins.value=await api('/api/admins')} async function loadPages(){pages.value=await api('/api/pages?admin='+encodeURIComponent(filters.admin))}
function setAdmin(a){filters.admin=a;filters.page_code='';setMinLeadsByAdmin();saveLocal();loadPages().then(()=>{if(isQueryPage.value){if(queryText.value.trim())runQuery()}else loadData()})}
function setPage(p){activePage.value=p;rows.value=[];total.value=0;closeDetail();filters.page_code='';queryStats.raw=0;queryStats.recognized=0;queryStats.returned=0;queryStats.unmatched=0;unmatchedList.value=[];error.value='';if(QUERY_PAGE_KEYS.has(p)){saveLocal();return}if(p==='foreignRef'){filters.sort_by='leads';filters.sort_dir='desc';saveLocal();loadRefMeta().then(()=>loadData());return}if(p==='church'){filters.sort_by='church';setChurchCycle(0,'church_current');return}else{filters.start_date=todayStr();filters.end_date=todayStr();quickMode.value='today';if(p==='posts')filters.date_type='lead';if(p==='invitesOverview'||p==='onlineOverview')filters.date_type='invite';if(p==='leads')filters.sort_by='leads';if(p==='invitesOverview')filters.sort_by='invites';if(p==='onlineOverview')filters.sort_by='online'} saveLocal();loadData()}
function quickDay(o){filters.start_date=todayStr(o);filters.end_date=todayStr(o);quickMode.value=o===0?'today':o===1?'yesterday':'before';saveLocal();loadData()}
function onDateInputChange(){quickMode.value='custom';scheduleFilterLoad()}
let filterLoadTimer=null
function scheduleFilterLoad(){if(isQueryPage.value)return;clearTimeout(filterLoadTimer);filterLoadTimer=setTimeout(()=>loadData(),350)}
function refreshData(){if(isQueryPage.value)return runQuery();return loadData()}
function queryApiPath(){if(activePage.value==='queryPostId')return '/api/query/by-post-id';if(activePage.value==='queryPostLink')return '/api/query/by-post-link';if(activePage.value==='queryLeadId')return '/api/query/by-lead-id';return ''}
async function runQuery(){if(!isQueryPage.value)return;const path=queryApiPath();if(!path)return;loading.value=true;error.value='';try{const d=await api(path,{method:'POST',body:JSON.stringify({text:queryText.value||'',admin:filters.admin,page_code:filters.page_code||null,limit:5000})});rows.value=Array.isArray(d.rows)?d.rows:[];total.value=Number(d.total||0);unmatchedList.value=Array.isArray(d.unmatched)?d.unmatched:[];const s=d.stats||{};queryStats.raw=Number(s.raw||0);queryStats.recognized=Number(s.recognized||0);queryStats.returned=Number(s.returned||total.value||0);queryStats.unmatched=Number(s.unmatched||unmatchedList.value.length||0);saveLocal()}catch(e){console.error('runQuery failed',e);rows.value=[];total.value=0;unmatchedList.value=[];queryStats.raw=0;queryStats.recognized=0;queryStats.returned=0;queryStats.unmatched=0;error.value='查询失败：'+(e.message||e)}finally{loading.value=false}}
function clearQuery(){queryText.value='';rows.value=[];total.value=0;queryStats.raw=0;queryStats.recognized=0;queryStats.returned=0;queryStats.unmatched=0;unmatchedList.value=[];closeDetail();error.value=''}
async function copyText(text,okMsg){
  if(text==null||text===''){alert('没有可复制的内容');return false}
  try{
    await navigator.clipboard.writeText(text)
    if(okMsg)flashCopyToast(okMsg)
    return true
  }catch{
    const ta=document.createElement('textarea')
    ta.value=text
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
    if(okMsg)flashCopyToast(okMsg)
    return true
  }
}
function copyCellValue(row,col){
  if(col.type==='image')return imageOf(row)||''
  if(col.type==='avatar')return row.page_avatar||''
  if(col.type==='link')return row[col.key]||''
  const v=formatCell(row,col)
  return v==null?'':String(v)
}
function tsvCell(s){
  const t=String(s??'')
  if(/[\t\n\r"]/.test(t))return '"'+t.replace(/"/g,'""')+'"'
  return t
}
async function copyCurrentResults(){
  if(!rows.value.length){alert('没有可复制的内容');return false}
  const cols=visibleColumns.value
  if(!cols.length){alert('没有可复制的列');return false}
  const header=cols.map(c=>tsvCell(c.label)).join('\t')
  const lines=rows.value.map(r=>cols.map(c=>tsvCell(copyCellValue(r,c))).join('\t'))
  return copyText([header,...lines].join('\n'),'已复制 '+rows.value.length+' 条')
}
async function copyUnmatched(){return copyText(unmatchedList.value.join('\n'),'已复制 '+unmatchedList.value.length+' 条未命中')}
async function loadData(){if(isQueryPage.value){if(queryText.value.trim())return runQuery();rows.value=[];total.value=0;unmatchedList.value=[];return}loading.value=true;error.value='';try{if(activePage.value==='foreignRef'){const p=new URLSearchParams();if(filters.ref_lang)p.set('lang',filters.ref_lang);if(filters.ref_post_type)p.set('post_type',filters.ref_post_type);p.set('min_leads',String(Number(filters.ref_min_leads)||0));if(filters.ref_start_date)p.set('start_date',filters.ref_start_date);if(filters.ref_end_date)p.set('end_date',filters.ref_end_date);p.set('sort_by',filters.sort_by||'leads');p.set('sort_dir',filters.sort_dir||'desc');p.set('limit','1000');const d=await api('/api/reference/posts?'+p.toString());rows.value=Array.isArray(d.rows)?d.rows:[];total.value=Number(d.total||0);saveLocal();return}const p=new URLSearchParams();p.set('admin',filters.admin); if(filters.page_code)p.set('page_code',filters.page_code); if(filters.start_date)p.set('start_date',filters.start_date); if(filters.end_date)p.set('end_date',filters.end_date); if(activePage.value==='posts'||activePage.value==='leads'){p.set('min_leads',String(Number(filters.min_leads)||0))}else{p.set('min_leads','0')} p.set('limit','1000'); let url='/api/posts?'; if(activePage.value==='church'){p.set('project','church');p.set('mode','all');p.set('sort_by',filters.sort_by||'church');p.set('sort_dir',filters.sort_dir||'desc');url='/api/project-posts?'} else if(activePage.value==='leads'){p.set('metric','leads');if(filters.sort_by)p.set('sort_by',filters.sort_by);p.set('sort_dir',filters.sort_dir||'desc');url='/api/ranking?'} else if(activePage.value==='invitesOverview'||activePage.value==='onlineOverview'){p.set('metric',activePage.value==='invitesOverview'?'invites':'online');p.set('date_type',filters.date_type||'invite');if(filters.sort_by)p.set('sort_by',filters.sort_by);p.set('sort_dir',filters.sort_dir||'desc');url='/api/overview?'} else {p.set('date_type',filters.date_type); if(filters.sort_by)p.set('sort_by',filters.sort_by); p.set('sort_dir',filters.sort_dir||'desc');url='/api/posts?'} const d=await api(url+p.toString());rows.value=Array.isArray(d.rows)?d.rows:[];total.value=Number(d.total||0);saveLocal()}catch(e){console.error('loadData failed',e);rows.value=[];total.value=0;error.value='数据加载失败：'+(e.message||e)}finally{loading.value=false}}
function saveLocal(){normalizeUi();localStorage.setItem(LOCAL_KEY,JSON.stringify({ui:JSON.parse(JSON.stringify(ui)),filters:JSON.parse(JSON.stringify(filters)),activePage:activePage.value,queryText:queryText.value}))}
let saveTimer=null
function saveLocalDebounced(){clearTimeout(saveTimer);saveTimer=setTimeout(()=>saveLocal(),500)}
watch(ui,saveLocalDebounced,{deep:true})
watch(filters,saveLocalDebounced,{deep:true})
watch(activePage,saveLocalDebounced)
watch(quickMode,saveLocalDebounced)
function restoreLocal(){const raw=localStorage.getItem(LOCAL_KEY);if(!raw)return;try{const d=JSON.parse(raw);if(d.ui)Object.assign(ui,d.ui);if(d.filters)Object.assign(filters,d.filters);if(d.activePage)activePage.value=d.activePage;if(typeof d.queryText==='string')queryText.value=d.queryText}catch{}}
function resetLocal(){localStorage.removeItem(LOCAL_KEY);location.reload()}
async function restoreAdminDefault(){localStorage.removeItem(LOCAL_KEY);await loadUi();normalizeUi();saveLocal();await loadData();alert('已恢复管理员默认设置')}
function formatDate(v){return v?String(v).replace('T',' ').slice(0,10):''}
function pct(n,d){return d?Math.round(n*100/d)+'%':'0%'}
function genderRatio(row){const m=Number(row.male)||0,f=Number(row.female)||0,t=m+f;return `男 ${pct(m,t)} / 女 ${pct(f,t)}`}
function formatCell(row,col){if(col.type==='gender_ratio')return genderRatio(row);if(col.type==='date')return formatDate(row[col.key]);return row[col.key]??''}
const SORTABLE_COLUMNS={leads:'leads',invites:'invites',online:'online',church:'church',post_likes:'post_likes',post_comments:'post_comments',post_shares:'post_shares'}
const FOREIGN_REF_SORTABLE=new Set(['leads','post_likes','post_comments','post_shares','post_time','post_type','lang_label'])
function sortKeyOf(c){if(isForeignRefPage.value)return FOREIGN_REF_SORTABLE.has(c.key)?c.key:'';return SORTABLE_COLUMNS[c.key]||''}
function isSortableColumn(c){return !!sortKeyOf(c)}
function sortByColumn(c){const k=sortKeyOf(c);if(!k)return;if(filters.sort_by===k){filters.sort_dir=filters.sort_dir==='asc'?'desc':'asc'}else{filters.sort_by=k;filters.sort_dir='desc'}saveLocal();loadData()}
function avatarText(v){const s=(v||'').toString().trim();return s?s.slice(0,1).toUpperCase():'—'}

function shortText(v){const s=v==null?'':String(v);return s.length>ui.textLimit?s.slice(0,ui.textLimit)+'...':s}
function imageOf(r){return r.display_media||r.image_link||''}
function openDetail(r,idx){
  hideCellTip()
  detail.value=r
  if(typeof idx==='number'&&idx>=0)detailIndex.value=idx
  else{
    const i=rows.value.findIndex(x=>x===r||(x.post_id&&r.post_id&&x.post_id===r.post_id))
    detailIndex.value=i
  }
}
function closeDetail(){detail.value=null;detailIndex.value=-1}
function detailNav(delta){
  const i=detailIndex.value+delta
  if(i<0||i>=rows.value.length)return
  detail.value=rows.value[i]
  detailIndex.value=i
  hideCellTip()
}
// 数据刷新后若当前详情已不在列表中则关闭
watch(rows,list=>{
  if(!detail.value)return
  if(detailIndex.value>=0&&detailIndex.value<list.length){
    detail.value=list[detailIndex.value]
    return
  }
  const i=list.findIndex(x=>x.post_id===detail.value.post_id)
  if(i>=0){detail.value=list[i];detailIndex.value=i}
  else closeDetail()
})
function headStyle(c){return {width:(c.width||100)+'px',minWidth:(c.width||100)+'px',background:ui.headerBg,color:ui.headerColor,borderColor:ui.gridColor,textAlign:c.align||'center'}}
function cellStyle(c){
  const s={width:(c.width||100)+'px',minWidth:(c.width||100)+'px',maxWidth:(c.width||100)+'px',borderColor:ui.gridColor,textAlign:c.align||'left'}
  if(c.displayMode==='lines'||c.displayMode==='wrap'){s.whiteSpace='normal';s.verticalAlign='top'}
  return s
}
function rowStyle(i){return {minHeight:ui.rowHeight+'px',background:i%2?ui.stripeBg:'#fff'}}
function reorder(arr){arr.forEach((c,i)=>c.order=i+1)}
function moveColumn(i,delta){const arr=sortedAllColumns.value;const j=i+delta;if(j<0||j>=arr.length)return;[arr[i],arr[j]]=[arr[j],arr[i]];reorder(arr);ui.columns=[...arr];saveLocal()}
function moveTop(i){const arr=sortedAllColumns.value;arr.unshift(arr.splice(i,1)[0]);reorder(arr);ui.columns=[...arr];saveLocal()}
function moveBottom(i){const arr=sortedAllColumns.value;arr.push(arr.splice(i,1)[0]);reorder(arr);ui.columns=[...arr];saveLocal()}
function dropColumn(i){const arr=sortedAllColumns.value;const from=dragIndex.value;if(from===null||from===i)return;const item=arr.splice(from,1)[0];arr.splice(i,0,item);reorder(arr);ui.columns=[...arr];dragIndex.value=null;saveLocal()}
function exportStyle(){saveLocal();const data={version:'v11',exportedAt:new Date().toISOString(),ui:JSON.parse(JSON.stringify(ui)),filters:JSON.parse(JSON.stringify(filters)),activePage:activePage.value};const blob=new Blob([JSON.stringify(data,null,2)],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='post-dashboard-style-v8-'+new Date().toISOString().slice(0,19).replace(/[:T]/g,'-')+'.json';a.click();URL.revokeObjectURL(a.href)}
async function importStyle(e){const f=e.target.files?.[0];if(!f)return;const txt=await f.text();const data=JSON.parse(txt);let cfg=data;if(data.localStorage){const key=Object.keys(data.localStorage).find(k=>/POST_DASHBOARD.*STATE/i.test(k));cfg=key?JSON.parse(data.localStorage[key]):data} if(cfg.ui)Object.assign(ui,cfg.ui); if(cfg.filters)Object.assign(filters,cfg.filters); if(cfg.activePage)activePage.value=cfg.activePage; normalizeUi();saveLocal();alert('已导入到当前浏览器')}
async function loginAdmin(){adminError.value='';try{const r=await fetch('/api/auth/admin',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:adminPassword.value})});if(!r.ok)throw new Error('管理员密码错误');const d=await r.json();adminToken.value=d.token;localStorage.setItem(ADMIN_KEY,d.token);await loadLogs()}catch(e){adminError.value=e.message}}
async function runSync(){adminError.value='正在同步，请等待...';try{const d=await api('/api/sync/run',{method:'POST'});adminError.value=d.message||'同步完成';await loadAdmins();await loadPages();if(isForeignRefPage.value)await loadRefMeta();await loadData();await loadLogs()}catch(e){adminError.value=e.message}}
async function runSyncForeign(){adminError.value='正在同步外语系参考，请等待...';try{const d=await api('/api/sync/run/foreign',{method:'POST'});adminError.value=d.message||'同步完成';if(isForeignRefPage.value)await loadRefMeta();await loadData();await loadLogs()}catch(e){adminError.value=e.message}}
async function loadLogs(){logs.value=await api('/api/sync/logs')}
let logPollTimer=null
watch([showAdmin,adminToken],([open,token])=>{
  if(logPollTimer){clearInterval(logPollTimer);logPollTimer=null}
  if(!open||!token)return
  loadLogs().catch(()=>{})
  logPollTimer=setInterval(()=>{loadLogs().catch(()=>{})},2500)
})
async function saveAdminUi(){normalizeUi();await fetch('/api/settings/ui',{method:'PUT',headers:headers(),body:JSON.stringify({value:ui})});adminError.value='已保存为管理员全局默认'}
async function clearSyncCache(){if(!confirm('确认清空同步缓存？会清空排行、项目、未匹配数据。'))return;await api('/api/settings/clear-sync-cache',{method:'POST'});adminError.value='已清空同步缓存'}
function onDetailKeydown(e){
  if(!detail.value)return
  if(e.key==='Escape'){closeDetail();return}
  if(e.key==='ArrowLeft'){e.preventDefault();detailNav(-1);return}
  if(e.key==='ArrowRight'){e.preventDefault();detailNav(1)}
}
onMounted(async()=>{
  window.addEventListener('keydown',onDetailKeydown)
  if(userToken.value){try{await init()}catch(e){localStorage.removeItem(USER_KEY);userToken.value=''}}
})
onBeforeUnmount(()=>{window.removeEventListener('keydown',onDetailKeydown);if(logPollTimer)clearInterval(logPollTimer)})
</script>
<style>
*{box-sizing:border-box}body{margin:0;font-family:Arial,"Microsoft YaHei",sans-serif;background:#f3f4f6;color:#111827}.app,.app *{font-size:inherit}button,.import-btn{cursor:pointer;border:1px solid #cbd5e1;background:white;border-radius:8px;padding:7px 11px;display:inline-flex;align-items:center}button:hover,button.active,.import-btn:hover{background:#16a34a;color:white;border-color:#16a34a}button:disabled{opacity:.4;cursor:not-allowed}button:disabled:hover{background:white;color:inherit;border-color:#cbd5e1}button.primary{background:#16a34a;color:white;border-color:#16a34a}button.primary:hover{filter:brightness(.95)}input,select{padding:7px;border:1px solid #cbd5e1;border-radius:8px}.login-wrap{min-height:100vh;display:flex;align-items:center;justify-content:center}.login-card{background:white;padding:30px;width:360px;border-radius:16px;box-shadow:0 10px 30px #0001;display:grid;gap:14px}.login-card h1,.topbar h1{font-size:20px;margin:0}.err{color:#dc2626}.topbar{display:flex;justify-content:space-between;align-items:center;padding:12px 18px;background:white;border-bottom:1px solid #e5e7eb}.top-actions,.admin-tabs,.page-tabs,.view-tabs,.modal-actions{display:flex;gap:8px;flex-wrap:wrap}.admin-tabs{padding:10px 16px 5px;background:#fff;border-bottom:1px dashed #e5e7eb}.page-tabs{padding:7px 16px 10px;background:#fff;border-bottom:1px solid #e5e7eb;align-items:center}.tabs-spacer{flex:1 1 24px;min-width:16px}.query-tab{border-radius:999px}.filters{margin:14px 16px;background:white;padding:14px;border-radius:14px;display:flex;gap:12px;flex-wrap:wrap;align-items:end}.filters label{display:grid;gap:4px;color:#475569}.filter-hint{color:#94a3b8;font-size:12px;align-self:center}.query-panel{margin:14px 16px;background:white;padding:14px;border-radius:14px;display:grid;gap:10px}.query-label{color:#334155;font-weight:600}.query-textarea{width:100%;min-height:140px;resize:vertical;padding:12px;border:1px solid #cbd5e1;border-radius:12px;font-family:inherit;line-height:1.5;background:#f8fafc}.query-textarea:focus{outline:none;border-color:#16a34a;box-shadow:0 0 0 3px #16a34a22;background:#fff}.query-actions{display:flex;gap:10px;flex-wrap:wrap;align-items:center}.query-stats{color:#64748b;font-size:13px}.unmatched-box{border:1px solid #fecaca;background:#fef2f2;border-radius:12px;padding:10px 12px}.unmatched-head{display:flex;gap:10px;align-items:center;margin-bottom:6px;color:#991b1b}.unmatched-list{margin:0;max-height:140px;overflow:auto;white-space:pre-wrap;word-break:break-all;background:transparent;padding:0;font-size:12px;color:#7f1d1d}.banner-err{margin:10px 16px 0;background:#fef2f2;border:1px solid #fecaca;color:#b91c1c;border-radius:10px;padding:10px 12px;display:flex;justify-content:space-between;align-items:flex-start;gap:12px}.banner-close{border:none;background:transparent;color:#b91c1c;font-size:18px;line-height:1;padding:0 4px}.empty-state{margin:24px 16px;background:white;border-radius:14px;padding:36px 20px;text-align:center;color:#64748b}.empty-state p{margin:0;font-size:14px;line-height:1.6}.view-tabs{margin:14px 16px;align-items:center}.loading-inline{color:#64748b;font-size:13px}.loading{margin:16px}.table-wrap{margin:16px;background:white;border-radius:14px;overflow:auto;max-height:calc(100vh - 245px)}table{border-collapse:collapse;width:max-content;min-width:100%}th,td{padding:7px 8px;vertical-align:middle;white-space:nowrap;border:1px solid var(--grid-color);overflow:hidden;text-overflow:ellipsis}td .cell-text{max-width:100%}table.noGrid th,table.noGrid td{border-color:transparent!important}thead th{position:sticky;top:0;z-index:2;font-weight:700}tbody tr:hover{background:var(--hover-bg)!important}.cell-popover{position:fixed;z-index:50;max-width:min(420px,calc(100vw - 24px));max-height:min(300px,45vh);padding:10px 12px;background:#111827;color:#f9fafb;border-radius:10px;box-shadow:0 12px 32px #00000040;font-size:13px;line-height:1.5;display:flex;flex-direction:column;gap:8px}.cell-popover-text{overflow:auto;max-height:min(240px,36vh);white-space:pre-wrap;word-break:break-word}.cell-popover-copy{align-self:flex-end;background:#16a34a;color:#fff;border:1px solid #15803d;border-radius:6px;padding:4px 10px;font-size:12px;cursor:pointer}.cell-popover-copy:hover{filter:brightness(1.05);background:#16a34a;color:#fff}.copy-toast{color:#15803d;font-size:12px;background:#dcfce7;border:1px solid #86efac;border-radius:999px;padding:3px 10px}.rowActive{outline:2px solid #86efac;outline-offset:-2px}.cardActive{box-shadow:0 0 0 2px #16a34a}.thumb{object-fit:cover;border-radius:8px;background:#f1f5f9}.avatar{width:32px;height:32px;border-radius:50%;object-fit:cover;vertical-align:middle;background:#e5e7eb;display:inline-flex;align-items:center;justify-content:center}.avatar-empty{color:#94a3b8}.cards{margin:16px;display:grid;grid-template-columns:repeat(auto-fill,minmax(360px,1fr));gap:16px}.cards.portrait{grid-template-columns:repeat(auto-fill,minmax(260px,1fr))}.card{background:white;border-radius:14px;overflow:hidden;box-shadow:0 4px 14px #0000000d}.media{background:#e2e8f0;display:flex;align-items:center;justify-content:center}.media img{width:100%;height:100%;object-fit:cover}.noimg{color:#64748b}.card-body{padding:12px;display:grid;gap:6px}.id{font-weight:bold}.meta,.nums,.ptype{color:#475569}.page-title{display:flex;align-items:center;gap:8px}.card-actions{display:flex;gap:8px;align-items:center}.drawer-mask{position:fixed;inset:0;background:#0f172a66;z-index:14;backdrop-filter:blur(1px)}.drawer{position:fixed;top:0;right:0;height:100vh;max-width:100vw;background:#fff;box-shadow:-12px 0 36px #00000022;z-index:15;display:flex;flex-direction:column;color:#111827}.drawer-head{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:10px 12px;border-bottom:1px solid #e5e7eb;background:#f8fafc;flex:0 0 auto}.drawer-nav{display:flex;align-items:center;gap:6px;flex-wrap:wrap}.drawer-nav button:disabled{opacity:.4;cursor:not-allowed}.drawer-pos{color:#64748b;font-size:12px;margin-left:4px}.drawer .close{float:none;font-size:22px;line-height:1;border:none;background:transparent;padding:4px 8px;color:#64748b}.drawer .close:hover{background:#e2e8f0;color:#0f172a}.drawer-body{flex:1 1 auto;min-height:0;overflow:auto;padding:12px 14px 24px;display:flex;flex-direction:column;gap:14px}.drawer-top{display:grid;grid-template-columns:140px 1fr;gap:12px;align-items:start}.drawer-media{display:flex;flex-direction:column;gap:8px;min-width:0}.drawer-hero{background:#f1f5f9;border-radius:10px;padding:8px;display:flex;align-items:center;justify-content:center;min-height:120px;min-width:0}.detail-img{max-height:180px;max-width:100%;width:auto;height:auto;object-fit:contain;border-radius:8px;display:block}.detail-noimg{color:#94a3b8;font-size:13px;padding:24px 8px}.drawer-summary{display:flex;flex-direction:column;gap:8px;min-width:0}.drawer-title-row{display:flex;align-items:center;gap:8px}.drawer-title-text{flex:1 1 auto;min-width:0;display:grid;gap:2px}.drawer-title-text b{font-size:15px;color:#111827}.drawer-link{display:inline-flex;align-self:stretch;justify-content:center;font-size:12px;padding:6px 8px;border:1px solid #bfdbfe;border-radius:8px;background:#eff6ff;text-decoration:none;color:#1d4ed8;text-align:center}.detail-stats{display:grid;grid-template-columns:repeat(2,1fr);gap:6px}.detail-stats.refStats{grid-template-columns:1fr}.detail-stats span{background:#f8fafc;border:1px solid #e5e7eb;border-radius:8px;padding:6px 4px;text-align:center;font-weight:700;font-size:14px;color:#111827}.detail-stats em{display:block;font-style:normal;font-weight:500;font-size:11px;color:#64748b;margin-bottom:2px}.detail-meta{display:grid;grid-template-columns:1fr 1fr;gap:6px 10px;font-size:12px;color:#111827}.detail-meta>div{display:grid;gap:2px;min-width:0}.detail-meta>div.full{grid-column:1/-1}.detail-meta label{color:#94a3b8;font-size:11px}.detail-meta .mono{font-family:ui-monospace,Consolas,monospace;word-break:break-all}.drawer-texts{display:flex;flex-direction:column;gap:10px}.drawer-section{border:1px solid #e5e7eb;border-radius:10px;background:#fff;overflow:hidden}.drawer-section.empty{opacity:.85}.drawer-section-head{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:8px 10px;background:#f8fafc;border-bottom:1px solid #e5e7eb}.drawer-section-head h3{margin:0;font-size:13px;font-weight:700;color:#111827}.sec-copy{padding:3px 8px;font-size:12px;border-radius:6px;border:1px solid #bbf7d0;background:#dcfce7;color:#15803d}.sec-copy:hover{background:#16a34a;color:#fff;border-color:#16a34a}.drawer-pre{margin:0;padding:10px 12px;background:#fff;color:#111827;font-size:13px;line-height:1.55;white-space:pre-wrap;word-break:break-word;min-height:2.5em;max-height:none;overflow:visible;font-family:inherit}.drawer-section.empty .drawer-pre{color:#94a3b8;font-style:italic}.muted{color:#64748b;font-size:12px}pre{white-space:pre-wrap;background:#f8fafc;padding:10px;border-radius:8px;color:#111827}
@media (max-width:560px){.drawer-top{grid-template-columns:1fr}.detail-img{max-height:140px}}.modal-mask{position:fixed;inset:0;background:#0006;display:flex;align-items:center;justify-content:center;z-index:20}.modal{background:white;width:700px;max-height:88vh;overflow:auto;border-radius:16px;padding:20px;display:grid;gap:12px}.settings-modal{width:1100px}.admin-modal{width:900px}.modal h2{font-size:20px;margin:0 0 8px}.modal h3{font-size:15px;margin:6px 0}.settings-grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.modal section{border:1px solid #e5e7eb;border-radius:12px;padding:12px;display:grid;gap:10px}.modal label{display:flex;justify-content:space-between;align-items:center;gap:12px}.column-settings{display:grid;gap:6px;max-height:420px;overflow:auto}.column-row{display:grid;grid-template-columns:30px 45px 160px 90px 80px 95px 80px 80px repeat(4,45px);gap:8px;align-items:center;padding:6px;border-bottom:1px solid #f1f5f9}.drag{cursor:move;color:#64748b}.admin-table{width:100%;font-size:12px}.admin-table td,.admin-table th{white-space:normal;border:1px solid #e5e7eb;vertical-align:top}.log-msg{white-space:pre-wrap;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:11px;line-height:1.4;max-height:180px;overflow:auto;max-width:520px}a{color:#2563eb}.sortable{cursor:pointer;user-select:none}.sortable:hover{filter:brightness(.96)}.sort-mark{margin-left:5px;font-weight:700;color:#16a34a}.sorted{box-shadow:inset 0 -2px 0 #16a34a}.label-input{width:100%;min-width:0}.avatar-empty{font-weight:700;color:#64748b;background:#e2e8f0}
</style>

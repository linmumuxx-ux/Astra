import { createApp } from 'vue'
import { ElAlert, ElButton, ElCollapse, ElCollapseItem, ElConfigProvider, ElDialog, ElDrawer, ElDropdown, ElDropdownItem, ElDropdownMenu, ElEmpty, ElForm, ElFormItem, ElInput, ElInputNumber, ElOption, ElRadioButton, ElRadioGroup, ElResult, ElSelect, ElSkeleton, ElSwitch, ElTable, ElTableColumn, ElTabPane, ElTabs, ElTag } from 'element-plus'
import 'element-plus/dist/index.css'
import './styles/tokens.css'
import './styles/element-plus-theme.css'
import './styles/app.css'
import App from './App.vue'
import { router } from './router'

const app = createApp(App).use(router)
app.use(ElAlert).use(ElButton).use(ElCollapse).use(ElCollapseItem).use(ElConfigProvider)
  .use(ElDialog).use(ElDrawer).use(ElDropdown).use(ElDropdownItem).use(ElDropdownMenu)
  .use(ElEmpty).use(ElForm).use(ElFormItem).use(ElInput).use(ElInputNumber).use(ElOption)
  .use(ElRadioButton).use(ElRadioGroup).use(ElResult).use(ElSelect).use(ElSkeleton)
  .use(ElSwitch).use(ElTable).use(ElTableColumn).use(ElTabPane).use(ElTabs).use(ElTag)
app.mount('#app')

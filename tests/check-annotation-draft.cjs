// Run: node tests/check-annotation-draft.cjs
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync('tools/annotation-workbench.html', 'utf8');
const validate = html.slice(html.indexOf('function validateDraft'), html.indexOf('try{const prior='));
const box = html.match(/function validBox[^\n]+/)[0];
const source = {id:'P001'};
const context = vm.createContext({WORK:{evaluation_inputs_id:'inputs',protocol_id:'protocol',index_id:'index',prediction:[source]}});
vm.runInContext(box + '\n' + validate, context);
const draft = {schema:'dsp-annotation-draft/1',evaluation_inputs_id:'inputs',protocol_id:'protocol',index_id:'index',training_authorized:false,status:'pending',reviewer:'test',records:{'prediction:P001':{mode:'prediction',reviewed:true,source,reviewer:'test',reviewed_at:'2026-09-14T00:00:00Z',note:'',ui_regions:[],region:[0,0,640,360],category:'waiting',items:[{type:'cursor',eligible:true,box:[0,0,10,10],expected:'test'}]}}};
context.validateDraft(draft);
for (const change of [d=>d.training_authorized=true,d=>d.status='passed',d=>d.records['prediction:P001'].items[0].box=null,d=>d.records['prediction:P001'].region=[0,0,100,100],d=>d.records['prediction:P001'].category='wrong',d=>d.records['prediction:P001'].ui_regions=[[0,0,-1,10]]]) {
    const bad = structuredClone(draft); change(bad);
    assert.throws(()=>context.validateDraft(bad));
}
const excluded = structuredClone(draft);
Object.assign(excluded.records['prediction:P001'], {reviewed:false,items:[],category:'',region:null,candidate_exclusion:'cannot classify'});
context.validateDraft(excluded);
console.log('annotation draft checks passed');

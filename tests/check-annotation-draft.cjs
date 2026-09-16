// Run: node tests/check-annotation-draft.cjs
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const html = fs.readFileSync('tools/annotation-workbench.html', 'utf8');
const validate = html.slice(html.indexOf('function validateDraft'), html.indexOf('try{const prior='));
const box = html.match(/function validBox[^\n]+/)[0];
const source = {artifact_id:'source',id:'P001',images:['history.png','step5.png','step15.png']};
const context = vm.createContext({WORK:{evaluation_inputs_id:'inputs',protocol_id:'protocol',index_id:'index',prediction:[source]}});
vm.runInContext(box + '\n' + validate, context);
const draft = {schema:'dsp-annotation-draft/1',evaluation_inputs_id:'inputs',protocol_id:'protocol',index_id:'index',training_authorized:false,status:'pending',reviewer:'test',records:{'prediction:P001':{mode:'prediction',reviewed:true,source,reviewer:'test',reviewed_at:'2026-09-14T00:00:00Z',note:'',ui_regions:[],region:[0,0,640,360],category:'waiting',items:[{type:'cursor',eligible:true,box:[0,0,10,10],expected:'test'}]}}};
context.validateDraft(draft);
const reordered=structuredClone(draft);
reordered.records['prediction:P001'].source=Object.fromEntries(Object.entries(source).reverse());
context.validateDraft(reordered);
for(const change of [s=>s.artifact_id='other',s=>s.images.reverse(),s=>s.extra=true,s=>delete s.artifact_id]){
    const bad=structuredClone(draft);change(bad.records['prediction:P001'].source);
    assert.throws(()=>context.validateDraft(bad));
}
for (const change of [d=>d.training_authorized=true,d=>d.status='passed',d=>d.records['prediction:P001'].items[0].box=null,d=>d.records['prediction:P001'].region=[0,0,100,100],d=>d.records['prediction:P001'].category='wrong',d=>d.records['prediction:P001'].ui_regions=[[0,0,-1,10]]]) {
    const bad = structuredClone(draft); change(bad);
    assert.throws(()=>context.validateDraft(bad));
}
const excluded = structuredClone(draft);
Object.assign(excluded.records['prediction:P001'], {reviewed:false,items:[],category:'',region:null,candidate_exclusion:'cannot classify'});
context.validateDraft(excluded);
// Optional payload comes from Python's actual on-disk atomic_save output.
if(process.argv[2]){
    const payload=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
    context.WORK=payload.work;context.validateDraft(payload.draft);
}
console.log('annotation draft checks passed');

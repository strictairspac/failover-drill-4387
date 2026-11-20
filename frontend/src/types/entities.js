/** @typedef {{id:number,name:string,role:'leader'|'follower',term:number,log_position:number,available:boolean,fenced:boolean,vote_enabled:boolean}} Node */
/** @typedef {{id:number,name:string,fail_primary:boolean,fence_primary:boolean,max_data_loss:number,required_term:number}} Scenario */
/** @typedef {{id:number,scenario_id:number,label:string,status:string,snapshot:object,result:object|null}} Drill */
/** @typedef {{id:number,generation:number,label:string,status:'active'|'retired',created_at:string,retired_at:string|null}} QuoteColumn */
/** @typedef {{id:number,seq:number,symbol:string,price:number|null,version:number|null}} QuoteRow */
/** @typedef {{token:string,generation:number,snapshot_version:number,last_seq:number,max_seq:number,status:string}} QuoteCursor */
export {};

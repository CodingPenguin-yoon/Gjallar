import CreateInstanceWizard from '../../components/CreateInstanceWizard'
import { useSearchParams } from 'react-router-dom'

export default function CreateVmPage(props) {
  const [search] = useSearchParams()
  const node = search.get('template_node') || ''
  const vmid = search.get('template_vmid') || ''
  const testTemplate = /^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(node) && /^[1-9][0-9]{2,8}$/.test(vmid)
    ? `${node}/${vmid}` : ''
  return <CreateInstanceWizard {...props} key={testTemplate || 'create'} testTemplate={testTemplate}
    config={testTemplate ? { creationMode: 'template', templateNodeId: node, templateVmid: Number(vmid),
      templateKey: testTemplate, powerPolicy: 'boot_and_verify' } : props.config} />
}

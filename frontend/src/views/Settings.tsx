import { useEffect, useState } from 'react';
import { 
  Settings as SettingsIcon, Shield, Database, Moon, Shuffle, 
  RefreshCw, Loader2, CheckCircle, AlertCircle, Key, UserCheck,
  Mail, ExternalLink, Copy
} from 'lucide-react';
import { api } from '../lib/api';
import { useToast } from '../components/Toast';

interface CredentialField {
  key: string;
  label: string;
  placeholder: string;
  help?: string;
  sensitive: boolean;
}

const CREDENTIAL_FIELDS: Record<string, CredentialField[]> = {
  x: [
    { key: 'CONTENTOS_X_ACCESS_TOKEN', label: 'Bearer Token', placeholder: 'AAAAAAAAAAAAAAAAAAAA...', help: 'https://developer.twitter.com/en/portal/dashboard', sensitive: true },
    { key: 'CONTENTOS_X_OAUTH_ACCESS_TOKEN', label: 'OAuth Access Token', placeholder: '2119489064017575937-...', help: 'https://developer.twitter.com/en/portal/dashboard', sensitive: true },
    { key: 'CONTENTOS_X_CONSUMER_KEY', label: 'Consumer Key (API Key)', placeholder: 'SC6tYJggABRkIJY95D6HwJny0', sensitive: true },
    { key: 'CONTENTOS_X_CONSUMER_SECRET', label: 'Consumer Secret', placeholder: 'Your consumer secret', sensitive: true },
    { key: 'CONTENTOS_X_ACCESS_TOKEN_SECRET', label: 'Access Token Secret', placeholder: 'Your access token secret', sensitive: true },
  ],
  openai: [
    { key: 'OPENAI_API_KEY', label: 'OpenAI API Key', placeholder: 'sk-...', help: 'https://platform.openai.com/api-keys', sensitive: true },
  ],
  stability: [
    { key: 'STABILITY_API_KEY', label: 'Stability AI API Key', placeholder: 'sk-...', help: 'https://platform.stability.ai', sensitive: true },
  ],
  replicate: [
    { key: 'REPLICATE_API_TOKEN', label: 'Replicate API Token', placeholder: 'r8_...', help: 'https://replicate.com', sensitive: true },
  ],
};

export default function Settings() {
  const [updateInfo, setUpdateInfo] = useState<{
    ok: boolean;
    current_version: string;
    latest_version: string;
    up_to_date: boolean;
    changelog?: string[];
    download_url?: string;
    note?: string;
  }>({ ok: true, current_version: '1.0.0', latest_version: '1.0.0', up_to_date: true });
  const [checking, setChecking] = useState(false);
  const [activeTab, setActiveTab] = useState<'update' | 'security' | 'accounts' | 'storage' | 'appearance'>('accounts');
  const { toast } = useToast();

  const checkForUpdate = async () => {
    setChecking(true);
    try {
      const data = await api.checkUpdate();
      setUpdateInfo(data);
      if (!data.up_to_date) {
        toast(`New version ${data.latest_version} available`, 'success');
      } else {
        toast('You are up to date', 'success');
      }
    } catch (e: any) {
      toast('Failed to check for updates', 'error');
    } finally {
      setChecking(false);
    }
  };

  useEffect(() => { checkForUpdate(); }, []);

  const copyCredentials = (provider: string) => {
    const lines = CREDENTIAL_FIELDS[provider as keyof typeof CREDENTIAL_FIELDS]
      .map(f => `${f.key}=<your_${f.label.toLowerCase().replace(/ /g, '_')}>`)
      .join('\n');
    navigator.clipboard.writeText(lines).then(() => 
      toast(`Copied template for ${provider}`, 'success')
    );
  };

  const tabs = [
    { id: 'accounts', label: 'Accounts & Keys', icon: UserCheck },
    { id: 'security', label: 'Security', icon: Shield },
    { id: 'storage', label: 'Storage', icon: Database },
    { id: 'appearance', label: 'Appearance', icon: Moon },
    { id: 'update', label: 'Updates', icon: Shuffle },
  ];

  return (
    <div className="h-full overflow-y-auto p-8 bg-canvas animate-fade-up">
      <div className="max-w-4xl mx-auto">
        {/* Header */}
        <div className="flex items-center gap-3 mb-8">
          <div className="w-11 h-11 rounded-xl bg-brand-50 border border-brand-200 flex items-center justify-center">
            <SettingsIcon size={20} className="text-brand-600" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-ink">Settings</h1>
            <p className="text-[13px] text-sub">Configure your ContentOS workspace.</p>
          </div>
        </div>

        {/* Tab Navigation */}
        <div className="card p-2 mb-6">
          <div className="flex flex-wrap gap-1">
            {tabs.map((tab) => {
              const Icon = tab.icon;
              const isActive = activeTab === tab.id;
              return (
                <button
                  key={tab.id}
                  onClick={() => setActiveTab(tab.id as any)}
                  className={`flex items-center gap-2 rounded-lg px-4 py-2 text-[13px] font-medium transition-all ${
                    isActive
                      ? 'bg-brand-500 text-white'
                      : 'text-sub hover:bg-edge hover:text-ink'
                  }`}
                >
                  <Icon size={14} />
                  {tab.label}
                </button>
              );
            })}
          </div>
        </div>

        {/* Accounts & API Keys Tab */}
        {activeTab === 'accounts' && (
          <div className="space-y-5">
            {/* X/Twitter Section */}
            <section className="card p-5">
              <h2 className="text-[12px] font-bold uppercase tracking-widest text-faint mb-4 flex items-center gap-2">
                <Mail size={14} /> X / Twitter
              </h2>
              <p className="text-[13px] text-sub mb-4 leading-relaxed">
                Connect your X/Twitter account to schedule posts. You need OAuth 1.0a credentials from the{' '}
                <a 
                  href="https://developer.twitter.com/en/portal/dashboard" 
                  target="_blank" 
                  rel="noopener noreferrer"
                  className="text-brand-500 hover:underline inline-flex items-center gap-1"
                >
                  Twitter Developer Portal <ExternalLink size={12} />
                </a>
              </p>
              
              <div className="border-t border-edge pt-4">
                <h3 className="text-[12px] font-bold uppercase tracking-widest text-sub mb-2">
                  Required Credentials
                </h3>
                <div className="bg-edge/30 rounded-lg p-3 mb-3">
                  <div className="text-[12px] text-faint mb-2">Add to <code className="bg-edge px-1.5 py-0.5 rounded font-mono">~/.secure_keys/.env</code>:</div>
                  <pre className="text-[11px] text-ink font-mono whitespace-pre-wrap">
{`CONTENTOS_X_ACCESS_TOKEN=your_bearer_token
CONTENTOS_X_OAUTH_ACCESS_TOKEN=your_oauth_token
CONTENTOS_X_CONSUMER_KEY=your_consumer_key
CONTENTOS_X_CONSUMER_SECRET=your_consumer_secret
CONTENTOS_X_ACCESS_TOKEN_SECRET=your_access_token_secret`}
                  </pre>
                  <button
                    onClick={() => copyCredentials('x')}
                    className="mt-2 flex items-center gap-1.5 text-[12px] text-brand-500 hover:underline"
                  >
                    <Copy size={12} /> Copy template
                  </button>
                </div>
                <p className="text-[11px] text-sub">
                  After adding credentials, restart the server for them to take effect.
                </p>
              </div>
            </section>

            {/* Image AI Providers Section */}
            <section className="card p-5 border-brand-200 bg-brand-50/30">
              <h2 className="text-[12px] font-bold uppercase tracking-widest text-faint mb-4 flex items-center gap-2">
                <Key size={14} /> Image Generation
              </h2>
              <p className="text-[13px] text-sub mb-4 leading-relaxed">
                Add API keys for cloud image generation (DALL-E 3, Stability AI, Replicate). 
                Otherwise, ContentOS will use your local Draw Things installation.
              </p>
              
              <div className="space-y-4">
                {(['openai', 'stability', 'replicate'] as const).map((provider) => (
                  <div key={provider} className="border border-edge rounded-lg p-3">
                    <div className="flex items-center justify-between mb-2">
                      <h3 className="text-[13px] font-medium text-ink capitalize">
                        {provider === 'replicate' ? 'Replicate (FLUX)' : provider}
                      </h3>
                    </div>
                    <div className="bg-edge/30 rounded-lg p-3 mb-2">
                      <pre className="text-[11px] text-ink font-mono whitespace-pre-wrap">
{`${CREDENTIAL_FIELDS[provider][0].key}=<your_api_key>`}
                      </pre>
                    </div>
                    <button
                      onClick={() => copyCredentials(provider)}
                      className="text-[12px] text-brand-500 hover:underline"
                    >
                      Copy template to clipboard
                    </button>
                  </div>
                ))}
              </div>
            </section>

            {/* GitHub Weekly Section */}
            <section className="card p-5 border-purple-200 bg-purple-50/30">
              <h2 className="text-[12px] font-bold uppercase tracking-widest text-faint mb-3 flex items-center gap-2">
                <AlertCircle size={14} /> GitHub Weekly
              </h2>
              <p className="text-[13px] text-sub mb-3">
                GitHub Weekly posts are generated using the platform's public API. No credentials are required.
              </p>
              <div className="text-[12px] text-faint">
                <span className="font-medium text-ink">Current Status:</span> Ready to generate weekly posts
              </div>
            </section>
          </div>
        )}

        {/* Security Tab */}
        {activeTab === 'security' && (
          <section className="card p-5">
            <h2 className="text-[12px] font-bold uppercase tracking-widest text-faint mb-4 flex items-center gap-2">
              <Shield size={14} /> Security
            </h2>
            <p className="text-[12px] text-faint mb-4">
              These protections are enforced by the local server and cannot be turned off here.
            </p>
            <div className="space-y-3">
              <div className="flex items-center justify-between text-[13px] text-sub">
                <span>Require human approval before any post publishes</span>
                <span className="flex items-center gap-1 text-emerald-600 text-[11px] font-semibold"><CheckCircle size={14} /> Enforced</span>
              </div>
              <div className="flex items-center justify-between text-[13px] text-sub">
                <span>Localhost-only host guard (127.0.0.1)</span>
                <span className="flex items-center gap-1 text-emerald-600 text-[11px] font-semibold"><CheckCircle size={14} /> Enforced</span>
              </div>
              <div className="border-t border-edge pt-4 mt-4">
                <h3 className="text-[12px] font-bold uppercase tracking-widest text-faint mb-2">Credential Storage</h3>
                <p className="text-[13px] text-sub leading-relaxed">
                  All API keys are stored in <code className="bg-edge px-1.5 py-0.5 rounded text-[12px] font-mono">~/.secure_keys/.env</code> 
                  and never committed to version control.
                </p>
              </div>
            </div>
          </section>
        )}

        {/* Storage Tab */}
        {activeTab === 'storage' && (
          <section className="card p-5">
            <h2 className="text-[12px] font-bold uppercase tracking-widest text-faint mb-4 flex items-center gap-2">
              <Database size={14} /> Storage
            </h2>
            <p className="text-[13px] text-sub leading-relaxed">
              Database is stored locally in your OS application-data folder. Nothing is uploaded to the cloud by default.
            </p>
          </section>
        )}

        {/* Updates Tab */}
        {activeTab === 'update' && (
          <section className="card p-5">
            <h2 className="text-[12px] font-bold uppercase tracking-widest text-faint mb-4 flex items-center gap-2">
              <Shuffle size={14} /> Auto-Update
            </h2>
            <div className="flex items-center justify-between mb-3">
              <div>
                <div className="text-[13px] font-medium text-ink">
                  {updateInfo.up_to_date ? (
                    <>
                      <CheckCircle size={16} className="inline text-green-500" /> You are up to date
                    </>
                  ) : (
                    <>
                      <AlertCircle size={16} className="inline text-amber-500" /> Update available
                    </>
                  )}
                </div>
                <div className="text-[12px] text-sub">Version {updateInfo.current_version}</div>
              </div>
              <button
                onClick={checkForUpdate}
                disabled={checking}
                className="flex items-center gap-2 rounded-lg border border-edge bg-surface px-3 py-2 text-[13px] font-medium hover:border-edgehover transition-colors"
              >
                {checking ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
                Check
              </button>
            </div>
            {updateInfo.note && (
              <p className="text-[12px] text-faint mt-2">Note: {updateInfo.note}</p>
            )}
          </section>
        )}

        {/* Appearance Tab */}
        {activeTab === 'appearance' && (
          <section className="card p-5">
            <h2 className="text-[12px] font-bold uppercase tracking-widest text-faint mb-4 flex items-center gap-2">
              <Moon size={14} /> Appearance
            </h2>
            <div className="flex items-center gap-3">
              <span className="text-[13px] text-sub">Theme</span>
              <div className="flex items-center gap-2">
                <span className="rounded-lg border border-brand-500 bg-brand-50 text-brand-700 px-3 py-1.5 text-[12px] font-semibold">Light</span>
                <span className="rounded-lg border border-edge bg-surface text-sub px-3 py-1.5 text-[12px] font-medium">Dark</span>
              </div>
            </div>
          </section>
        )}
      </div>
    </div>
  );
}
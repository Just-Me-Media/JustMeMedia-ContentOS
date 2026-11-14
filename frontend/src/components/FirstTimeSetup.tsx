import { useState, useEffect } from 'react';
import { Rss, Key, Shield, ExternalLink } from 'lucide-react';
import { api } from '../lib/api';

interface SetupStep {
  id: string;
  title: string;
  description: string;
  icon: typeof Rss;
}

const SETUP_STEPS: SetupStep[] = [
  {
    id: 'sources',
    title: 'Add Your Sources',
    description: 'Add RSS feeds you want to monitor. ContentOS will scan them daily for new stories.',
    icon: Rss,
  },
  {
    id: 'credentials',
    title: 'Connect Social Accounts',
    description: 'Add your X/Twitter API keys to enable publishing. Local image generation works out of the box.',
    icon: Key,
  },
  {
    id: 'review',
    title: 'Review Your Setup',
    description: 'Visit the Review Queue to see queued drafts, then start creating content.',
    icon: Shield,
  },
];

export default function FirstTimeSetup({ onComplete }: { onComplete: () => void }) {
  const [currentStep, setCurrentStep] = useState(0);

  const handleSkip = () => {
    localStorage.setItem('contentos-setup-complete', 'true');
    onComplete();
  };

  const handleNext = async () => {
    if (currentStep < SETUP_STEPS.length - 1) {
      setCurrentStep(currentStep + 1);
    }
  };

  const handleBack = () => {
    if (currentStep > 0) {
      setCurrentStep(currentStep - 1);
    }
  };

  // Check if user has any watchlist items or credentials
  useEffect(() => {
    const checkSetupStatus = async () => {
      try {
        const watchlist = await api.getWatchlist();
        if (watchlist.items && watchlist.items.length > 0) {
          localStorage.setItem('contentos-setup-complete', 'true');
          onComplete();
        }
      } catch {
        // No watchlist yet, continue setup
      }
    };
    checkSetupStatus();
  }, []);

  const StepIcon = SETUP_STEPS[currentStep]?.icon || Rss;

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-[100] flex items-center justify-center p-4">
      <div className="bg-surface rounded-xl shadow-2xl max-w-md w-full p-6">
        <div className="flex items-center gap-3 mb-6">
          <div className="w-10 h-10 rounded-lg bg-brand-500 text-white flex items-center justify-center">
            <StepIcon size={20} />
          </div>
          <div>
            <h2 className="text-xl font-bold text-ink">
              {SETUP_STEPS[currentStep]?.title || 'Welcome'}
            </h2>
            <p className="text-[13px] text-sub">Step {currentStep + 1} of {SETUP_STEPS.length}</p>
          </div>
        </div>

        <div className="mb-6">
          <h3 className="text-[13px] font-medium text-ink mb-2">
            {SETUP_STEPS[currentStep]?.description || 'Welcome to ContentOS!'}
          </h3>
          {currentStep === 0 && (
            <div className="text-[13px] text-sub leading-relaxed">
              <p>✅ Start with curated feeds:</p>
              <ul className="list-disc list-inside text-sm mt-1 space-y-1 ml-4">
                <li>TechCrunch Breaking News</li>
                <li>Hacker News</li>
                <li>OpenAI News</li>
                <li>WIRED</li>
              </ul>
              <p className="mt-2">Or add your own RSS feeds in Sources → Watchlist.</p>
            </div>
          )}
          {currentStep === 1 && (
            <div className="text-[13px] text-sub leading-relaxed space-y-3">
              <div>
                <p className="font-medium text-ink mb-1">🖼 Local image generation (free, macOS)</p>
                <ul className="space-y-1 ml-1">
                  <li>
                    <a
                      href="https://apps.apple.com/us/app/draw-things-ai-generation/id6444050820"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-brand-500 hover:underline inline-flex items-center gap-1"
                    >
                      Download Draw Things from the App Store <ExternalLink size={11} />
                    </a>
                  </li>
                  <li className="text-sub">
                    Then open Draw Things → <strong>Settings → API Server</strong> → enable on port 7860
                  </li>
                </ul>
              </div>
              <div>
                <p className="font-medium text-ink mb-1">☁️ Cloud image providers (optional)</p>
                <p className="text-sub">Add API keys in Settings for DALL-E 3, Stability AI, or Replicate.</p>
              </div>
              <div>
                <p className="font-medium text-ink mb-1">🐦 Social publishing</p>
                <a
                  href="https://developer.twitter.com/en/portal/dashboard"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-brand-500 hover:underline inline-flex items-center gap-1"
                >
                  Get X/Twitter API keys <ExternalLink size={11} />
                </a>
              </div>
            </div>
          )}
          {currentStep === 2 && (
            <div className="text-[13px] text-sub leading-relaxed">
              <p>✅ You're ready to go!</p>
              <ul className="text-sm mt-1 space-y-1">
                <li><strong>Discover</strong> - Browse feeds and create drafts</li>
                <li><strong>Queue</strong> - Review and approve drafts</li>
                <li><strong>Calendar</strong> - Schedule posts</li>
              </ul>
            </div>
          )}
        </div>

        <div className="flex justify-between items-center">
          <button
            onClick={handleSkip}
            className="text-[12px] text-sub hover:text-ink transition-colors"
          >
            Skip setup
          </button>
          <div className="flex gap-2">
            {currentStep > 0 && (
              <button
                onClick={handleBack}
                className="px-4 py-2 rounded-lg border border-edge text-[13px] text-sub hover:border-edgehover transition-colors"
              >
                Back
              </button>
            )}
            <button
              onClick={handleNext}
              className="px-4 py-2 rounded-lg bg-brand-500 text-white text-[13px] font-medium hover:bg-brand-600 transition-colors"
            >
              {currentStep < SETUP_STEPS.length - 1 ? 'Next' : 'Get Started'}
            </button>
          </div>
        </div>

        {currentStep === SETUP_STEPS.length - 1 && (
          <button
            onClick={handleSkip}
            className="w-full mt-4 px-4 py-2 rounded-lg bg-green-500 text-white text-[13px] font-medium hover:bg-green-600 transition-colors"
          >
            Go to Dashboard
          </button>
        )}
      </div>
    </div>
  );
}
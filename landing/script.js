// ───────── Tab switching for the Screens section ─────────
const tabs = document.querySelectorAll('.tab')
const panes = document.querySelectorAll('.screen-pane')

tabs.forEach(tab => {
  tab.addEventListener('click', () => {
    const target = tab.dataset.tab
    tabs.forEach(t => t.classList.toggle('active', t === tab))
    panes.forEach(p => p.classList.toggle('active', p.dataset.pane === target))
  })
})

// ───────── Mobile nav toggle ─────────
const navToggle = document.querySelector('.nav-toggle')
const navLinks = document.querySelector('.nav-links')
if (navToggle && navLinks) {
  navToggle.addEventListener('click', () => {
    navLinks.classList.toggle('open')
    navLinks.style.display = navLinks.classList.contains('open') ? 'flex' : ''
  })
}

// ───────── GitHub link placeholder ─────────
// Replace these once the repo is published.
const GITHUB_URL = 'https://github.com/#'
document.querySelectorAll('#githubLink, #githubLink2').forEach(a => {
  a.href = GITHUB_URL
  a.target = '_blank'
  a.rel = 'noopener'
})

// ───────── Smooth scroll for anchor links ─────────
document.querySelectorAll('a[href^="#"]').forEach(a => {
  a.addEventListener('click', (e) => {
    const href = a.getAttribute('href')
    if (href === '#' || href.length < 2) return
    const target = document.querySelector(href)
    if (!target) return
    e.preventDefault()
    const top = target.getBoundingClientRect().top + window.scrollY - 72
    window.scrollTo({ top, behavior: 'smooth' })
    // Close mobile nav if open
    if (navLinks?.classList.contains('open')) {
      navLinks.classList.remove('open')
      navLinks.style.display = ''
    }
  })
})

// ───────── Subtle reveal-on-scroll for sections ─────────
if ('IntersectionObserver' in window) {
  const io = new IntersectionObserver((entries) => {
    entries.forEach(e => {
      if (e.isIntersecting) {
        e.target.style.opacity = '1'
        e.target.style.transform = 'none'
        io.unobserve(e.target)
      }
    })
  }, { threshold: 0.08, rootMargin: '0px 0px -10% 0px' })

  document.querySelectorAll('.feature, .stack-card, .why-card, .how-step').forEach(el => {
    el.style.opacity = '0'
    el.style.transform = 'translateY(20px)'
    el.style.transition = 'opacity .55s ease, transform .55s ease'
    io.observe(el)
  })
}

import * as functions from 'firebase-functions';
import * as admin from 'firebase-admin';
import Stripe from 'stripe';

admin.initializeApp();

const db = admin.firestore();

// Initialize Stripe (API key will be set via Firebase config)
const getStripe = () => {
  const stripeKey = process.env.STRIPE_SECRET_KEY || functions.config().stripe?.secret_key;
  if (!stripeKey) {
    throw new Error('Stripe secret key not configured');
  }
  return new Stripe(stripeKey, { apiVersion: '2024-12-18.acacia' });
};

// User document interface
interface UserDoc {
  email: string;
  createdAt: admin.firestore.Timestamp;
  songsProcessed: number;
  subscription: {
    status: 'none' | 'active' | 'canceled' | 'past_due';
    stripeCustomerId: string | null;
    stripeSubscriptionId: string | null;
    currentPeriodEnd: admin.firestore.Timestamp | null;
  };
}

// Free tier limit
const FREE_SONGS_LIMIT = 5;

/**
 * Auth trigger: Create user document when a new user signs up
 */
export const createUser = functions.auth.user().onCreate(async (user) => {
  const userDoc: UserDoc = {
    email: user.email || '',
    createdAt: admin.firestore.Timestamp.now(),
    songsProcessed: 0,
    subscription: {
      status: 'none',
      stripeCustomerId: null,
      stripeSubscriptionId: null,
      currentPeriodEnd: null
    }
  };

  await db.collection('users').doc(user.uid).set(userDoc);
  console.log(`Created user document for ${user.uid}`);
});

/**
 * Callable function: Increment usage count after successful export
 */
export const incrementUsage = functions.https.onCall(async (data, context) => {
  if (!context.auth) {
    throw new functions.https.HttpsError('unauthenticated', 'Must be logged in');
  }

  const uid = context.auth.uid;
  const userRef = db.collection('users').doc(uid);

  await db.runTransaction(async (transaction) => {
    const userDoc = await transaction.get(userRef);

    if (!userDoc.exists) {
      throw new functions.https.HttpsError('not-found', 'User document not found');
    }

    const userData = userDoc.data() as UserDoc;

    // Check if user can process (has subscription or under free limit)
    const canProcess =
      userData.subscription.status === 'active' ||
      userData.songsProcessed < FREE_SONGS_LIMIT;

    if (!canProcess) {
      throw new functions.https.HttpsError(
        'resource-exhausted',
        'Free tier limit reached. Please subscribe to continue.'
      );
    }

    transaction.update(userRef, {
      songsProcessed: admin.firestore.FieldValue.increment(1)
    });
  });

  return { success: true };
});

/**
 * Callable function: Check if user can process a song
 */
export const canProcessSong = functions.https.onCall(async (data, context) => {
  if (!context.auth) {
    throw new functions.https.HttpsError('unauthenticated', 'Must be logged in');
  }

  const uid = context.auth.uid;
  const userDoc = await db.collection('users').doc(uid).get();

  if (!userDoc.exists) {
    throw new functions.https.HttpsError('not-found', 'User document not found');
  }

  const userData = userDoc.data() as UserDoc;

  const canProcess =
    userData.subscription.status === 'active' ||
    userData.songsProcessed < FREE_SONGS_LIMIT;

  return {
    canProcess,
    songsProcessed: userData.songsProcessed,
    songsRemaining: userData.subscription.status === 'active'
      ? -1 // unlimited
      : Math.max(0, FREE_SONGS_LIMIT - userData.songsProcessed),
    isSubscribed: userData.subscription.status === 'active'
  };
});

/**
 * Callable function: Create a Stripe Checkout session
 */
export const createCheckoutSession = functions.https.onCall(async (data, context) => {
  if (!context.auth) {
    throw new functions.https.HttpsError('unauthenticated', 'Must be logged in');
  }

  const stripe = getStripe();
  const uid = context.auth.uid;
  const userDoc = await db.collection('users').doc(uid).get();

  if (!userDoc.exists) {
    throw new functions.https.HttpsError('not-found', 'User document not found');
  }

  const userData = userDoc.data() as UserDoc;

  // Get or create Stripe customer
  let customerId = userData.subscription.stripeCustomerId;

  if (!customerId) {
    const customer = await stripe.customers.create({
      email: userData.email,
      metadata: { firebaseUid: uid }
    });
    customerId = customer.id;

    await db.collection('users').doc(uid).update({
      'subscription.stripeCustomerId': customerId
    });
  }

  // Create checkout session
  const priceId = process.env.STRIPE_PRICE_ID || functions.config().stripe?.price_id;
  if (!priceId) {
    throw new functions.https.HttpsError('failed-precondition', 'Stripe price not configured');
  }

  const session = await stripe.checkout.sessions.create({
    customer: customerId,
    payment_method_types: ['card'],
    line_items: [
      {
        price: priceId,
        quantity: 1
      }
    ],
    mode: 'subscription',
    success_url: data.successUrl || 'cleanse://subscription-success',
    cancel_url: data.cancelUrl || 'cleanse://subscription-canceled',
    metadata: { firebaseUid: uid }
  });

  return { sessionId: session.id, url: session.url };
});

/**
 * Callable function: Create a Stripe Customer Portal session
 */
export const createPortalSession = functions.https.onCall(async (data, context) => {
  if (!context.auth) {
    throw new functions.https.HttpsError('unauthenticated', 'Must be logged in');
  }

  const stripe = getStripe();
  const uid = context.auth.uid;
  const userDoc = await db.collection('users').doc(uid).get();

  if (!userDoc.exists) {
    throw new functions.https.HttpsError('not-found', 'User document not found');
  }

  const userData = userDoc.data() as UserDoc;
  const customerId = userData.subscription.stripeCustomerId;

  if (!customerId) {
    throw new functions.https.HttpsError('failed-precondition', 'No Stripe customer found');
  }

  const session = await stripe.billingPortal.sessions.create({
    customer: customerId,
    return_url: data.returnUrl || 'cleanse://settings'
  });

  return { url: session.url };
});

/**
 * HTTP endpoint: Stripe webhook handler
 */
export const stripeWebhook = functions.https.onRequest(async (req, res) => {
  const stripe = getStripe();
  const webhookSecret = process.env.STRIPE_WEBHOOK_SECRET || functions.config().stripe?.webhook_secret;

  if (!webhookSecret) {
    console.error('Stripe webhook secret not configured');
    res.status(500).send('Webhook secret not configured');
    return;
  }

  const signature = req.headers['stripe-signature'] as string;

  let event: Stripe.Event;

  try {
    event = stripe.webhooks.constructEvent(req.rawBody, signature, webhookSecret);
  } catch (err) {
    console.error('Webhook signature verification failed:', err);
    res.status(400).send(`Webhook Error: ${(err as Error).message}`);
    return;
  }

  // Handle the event
  switch (event.type) {
    case 'customer.subscription.created':
    case 'customer.subscription.updated': {
      const subscription = event.data.object as Stripe.Subscription;
      await handleSubscriptionUpdate(subscription);
      break;
    }

    case 'customer.subscription.deleted': {
      const subscription = event.data.object as Stripe.Subscription;
      await handleSubscriptionDeleted(subscription);
      break;
    }

    case 'checkout.session.completed': {
      const session = event.data.object as Stripe.Checkout.Session;
      console.log('Checkout completed:', session.id);
      // Subscription will be handled by customer.subscription.created
      break;
    }

    default:
      console.log(`Unhandled event type: ${event.type}`);
  }

  res.status(200).send('OK');
});

async function handleSubscriptionUpdate(subscription: Stripe.Subscription) {
  const customerId = subscription.customer as string;

  // Find user by Stripe customer ID
  const usersSnapshot = await db.collection('users')
    .where('subscription.stripeCustomerId', '==', customerId)
    .limit(1)
    .get();

  if (usersSnapshot.empty) {
    console.error(`No user found for Stripe customer ${customerId}`);
    return;
  }

  const userDoc = usersSnapshot.docs[0];
  const status = mapStripeStatus(subscription.status);

  await userDoc.ref.update({
    'subscription.status': status,
    'subscription.stripeSubscriptionId': subscription.id,
    'subscription.currentPeriodEnd': admin.firestore.Timestamp.fromMillis(
      subscription.current_period_end * 1000
    )
  });

  console.log(`Updated subscription for user ${userDoc.id}: ${status}`);
}

async function handleSubscriptionDeleted(subscription: Stripe.Subscription) {
  const customerId = subscription.customer as string;

  const usersSnapshot = await db.collection('users')
    .where('subscription.stripeCustomerId', '==', customerId)
    .limit(1)
    .get();

  if (usersSnapshot.empty) {
    console.error(`No user found for Stripe customer ${customerId}`);
    return;
  }

  const userDoc = usersSnapshot.docs[0];

  await userDoc.ref.update({
    'subscription.status': 'canceled',
    'subscription.stripeSubscriptionId': null,
    'subscription.currentPeriodEnd': null
  });

  console.log(`Subscription canceled for user ${userDoc.id}`);
}

function mapStripeStatus(stripeStatus: Stripe.Subscription.Status): UserDoc['subscription']['status'] {
  switch (stripeStatus) {
    case 'active':
    case 'trialing':
      return 'active';
    case 'past_due':
      return 'past_due';
    case 'canceled':
    case 'unpaid':
    case 'incomplete':
    case 'incomplete_expired':
    case 'paused':
      return 'canceled';
    default:
      return 'none';
  }
}
